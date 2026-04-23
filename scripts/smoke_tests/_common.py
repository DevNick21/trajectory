"""Shared smoke-test plumbing.

Responsibilities:
  - Put `src/` on sys.path so `trajectory.*` imports work regardless of
    where the script is invoked from.
  - Redirect `settings.sqlite_db_path` and `settings.faiss_index_path`
    to a fresh temp dir per run so real-API smoke tests never touch the
    project's SQLite DB / FAISS index.
  - Disable Managed Agents by default — the plain Messages API is easier
    to debug when a smoke test fails.
  - Provide a uniform `SmokeResult` + `run_smoke(name, coro)` wrapper so
    `run_all.py` can aggregate results without boilerplate.

Every smoke test module exports exactly one coroutine:

    async def run() -> SmokeResult: ...

`run_all.py` discovers them via the _REGISTRY list below.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

# ---------------------------------------------------------------------------
# sys.path — do this before importing anything from trajectory
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures"
FIXTURE_BUNDLE = _FIXTURE_DIR / "sample_research_bundle.json"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"smoke.{name}")
    if not logger.handlers:
        # run_all configures the root logger; individual modules just
        # grab a namespaced logger.
        pass
    return logger


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SmokeResult:
    name: str
    passed: bool
    duration_s: float
    messages: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    error: Optional[str] = None

    def summary(self) -> str:
        flag = "PASS" if self.passed else "FAIL"
        cost = (
            f" (~${self.estimated_cost_usd:.3f})"
            if self.estimated_cost_usd > 0
            else ""
        )
        return f"[{flag}] {self.name} ({self.duration_s:.2f}s{cost})"


# ---------------------------------------------------------------------------
# Environment setup — call once from run_all or from a single-module run
# ---------------------------------------------------------------------------


_ENV_SET_UP = False


def prepare_environment() -> Path:
    """Redirect SQLite + FAISS paths to a per-run tempdir and disable
    Managed Agents. Safe to call multiple times — only the first call
    mutates `settings`.

    Returns the tempdir path so callers can inspect / clean up.
    """
    global _ENV_SET_UP
    tmp = Path(tempfile.mkdtemp(prefix="trajectory-smoke-"))
    if _ENV_SET_UP:
        return tmp

    # Import `settings` lazily — pydantic-settings reads .env at import
    # time, and we want .env-driven keys (ANTHROPIC_API_KEY,
    # TELEGRAM_BOT_TOKEN, COMPANIES_HOUSE_API_KEY) to flow through.
    from trajectory.config import settings

    settings.sqlite_db_path = tmp / "smoke.db"
    settings.faiss_index_path = tmp / "smoke.faiss"
    settings.use_managed_agents = False

    _ENV_SET_UP = True
    return tmp


def require_anthropic_key() -> Optional[str]:
    """Return an error message if the Anthropic key isn't wired anywhere,
    else None.
    """
    from trajectory.config import settings

    if not settings.anthropic_api_key:
        return (
            "ANTHROPIC_API_KEY is not set in .env or the environment. "
            "This smoke test makes a real Opus call and cannot run "
            "without it."
        )
    return None


def require_env(name: str) -> Optional[str]:
    """Generic env guard — reads from os.environ OR settings by
    attribute name. Returns an error message or None.
    """
    from trajectory.config import settings

    attr = name.lower()
    if getattr(settings, attr, None):
        return None
    if os.getenv(name):
        return None
    return f"{name} is not set in .env or the environment."


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def load_fixture_bundle():
    from trajectory.schemas import ResearchBundle

    if not FIXTURE_BUNDLE.exists():
        raise FileNotFoundError(f"Fixture not found: {FIXTURE_BUNDLE}")
    data = json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))
    data.setdefault("bundle_completed_at", now_utc_naive().isoformat())
    return ResearchBundle.model_validate(data)


def build_test_user(user_type: str = "visa_holder"):
    from trajectory.schemas import UserProfile, VisaStatus

    now = now_utc_naive()
    visa_status = None
    if user_type == "visa_holder":
        visa_status = VisaStatus(route="graduate", expiry_date=date(2027, 9, 30))
    return UserProfile(
        user_id=f"smoke_{user_type}",
        name="Smoke Test",
        user_type=user_type,
        visa_status=visa_status,
        base_location="London",
        salary_floor=45_000,
        salary_target=60_000,
        motivations=["shipping products people use", "technical leadership"],
        deal_breakers=["pure maintenance work", "no remote flexibility"],
        good_role_signals=["strong engineering culture", "fast-growing team"],
        life_constraints=[],
        search_started_date=date(2025, 10, 1),
        current_employment="EMPLOYED",
        created_at=now,
        updated_at=now,
    )


def build_test_session(user_id: str, intent: str = "forward_job"):
    from trajectory.schemas import Session

    return Session(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        intent=intent,
        job_url="https://example.com/job/smoke-test",
        created_at=now_utc_naive(),
    )


# ---------------------------------------------------------------------------
# Wrapper: converts exceptions / timing / failures-list into a SmokeResult
# ---------------------------------------------------------------------------


async def run_smoke(
    name: str,
    coro: Callable[[], Awaitable[tuple[list[str], list[str], float]]],
) -> SmokeResult:
    """Wrap a smoke-test body. The body returns
        (messages, failures, estimated_cost_usd)
    and raises on unhandled errors.
    """
    log = get_logger(name)
    log.info("-- %s --", name)
    started = time.monotonic()
    try:
        messages, failures, cost = await coro()
    except Exception as exc:
        return SmokeResult(
            name=name,
            passed=False,
            duration_s=time.monotonic() - started,
            failures=[f"unhandled exception: {exc!r}"],
            error=traceback.format_exc(),
        )
    passed = not failures
    return SmokeResult(
        name=name,
        passed=passed,
        duration_s=time.monotonic() - started,
        messages=messages,
        failures=failures,
        estimated_cost_usd=cost,
    )
