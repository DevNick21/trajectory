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

# Allow Settings to boot without DEMO_USER_ID / TELEGRAM_BOT_TOKEN in the
# environment. Individual smoke tests that need those values set them
# explicitly on `settings` after `prepare_environment()`. Must be set
# BEFORE the first `from trajectory.config import settings` anywhere.
os.environ.setdefault("TRAJECTORY_TEST_MODE", "1")

# Windows console defaults to cp1252 — Unicode arrows / em-dashes /
# emojis in `messages` (and the bot's emoji prompts) crash a standalone
# smoke test on `print(...)` even though the test itself passed. The
# `run_all.py` runner already does this; replicate it here so a
# direct `python -m scripts.smoke_tests.<name>` doesn't crash the
# trailing print loop. Mirrors run_all.py:34-39.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover
        pass

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
    settings.enable_managed_company_investigator = False

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


def build_synthetic_writing_style(user_id: str = "smoke_user", sample_count: int = 3):
    """Hand-built WritingStyleProfile for tests that need a style input but
    don't care about the LLM-extracted content."""
    from trajectory.schemas import WritingStyleProfile

    now = now_utc_naive()
    return WritingStyleProfile(
        profile_id=f"smoke_style_{user_id}",
        user_id=user_id,
        tone="plainspoken, technical",
        sentence_length_pref="varied",
        formality_level=6,
        hedging_tendency="direct",
        signature_patterns=["leads with the result", "uses numbers not adjectives"],
        avoided_patterns=["buzzwords", "vague corporate speak"],
        examples=["Cut p99 from 600ms to 195ms.", "Owned migration end-to-end."],
        source_sample_ids=[f"sample_{i}" for i in range(sample_count)],
        sample_count=sample_count,
        created_at=now,
        updated_at=now,
    )


def build_synthetic_cv_output(name: str = "Smoke Test"):
    """Minimal, renderer-safe CVOutput. Citations point into the fixture
    research bundle so the citation validator passes against that ctx.
    """
    from trajectory.schemas import CVBullet, CVOutput, CVRole, Citation

    fixture_url = "https://acmetech.io/careers"
    fixture_snippet = "Our engineering team ships autonomously."

    bullet = CVBullet(
        text="Shipped distributed payment pipeline serving 1M+ RPS.",
        citations=[Citation(
            kind="url_snippet",
            url=fixture_url,
            verbatim_snippet=fixture_snippet,
        )],
    )
    role = CVRole(
        title="Senior Software Engineer",
        company="Example Corp",
        dates="2022 — Present",
        bullets=[bullet, bullet],
    )
    return CVOutput(
        name=name,
        contact={
            "email": "smoke@example.com",
            "phone": "+44 20 7946 0018",
            "location": "London",
            "linkedin": "linkedin.com/in/smoketest",
            "github": "github.com/smoketest",
        },
        professional_summary=(
            "Backend engineer with seven years shipping production Python services."
        ),
        experience=[role],
        education=[{
            "degree": "BSc Computer Science",
            "institution": "University of Example",
            "dates": "2015 — 2018",
        }],
        skills=["Python", "Kubernetes", "PostgreSQL", "AWS"],
        projects=None,
    )


def build_synthetic_cover_letter_output():
    from trajectory.schemas import Citation, CoverLetterOutput

    citations = [
        Citation(
            kind="url_snippet",
            url="https://acmetech.io/careers",
            verbatim_snippet="Our engineering team ships autonomously.",
        ),
    ]
    paragraphs = [
        "Opening paragraph referencing Acme's published engineering culture.",
        "Middle paragraph tying a specific STAR-style achievement to the role.",
        "Closing paragraph with a concrete ask and a pointer to attached materials.",
    ]
    text = " ".join(paragraphs)
    return CoverLetterOutput(
        addressed_to="Hiring Team, Acme Tech Ltd",
        paragraphs=paragraphs,
        citations=citations,
        word_count=len(text.split()),
    )


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
