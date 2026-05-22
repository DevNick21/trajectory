"""Runtime configuration — single source of truth for env vars and paths.

Everything that reads `.env` or hardcoded paths goes through `settings`. Do
not read `os.environ` directly elsewhere in the codebase.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_test_env() -> bool:
    """True when we're running under pytest or explicitly in test mode.

    Used to relax required-secrets validation so tests can construct
    Settings() without real credentials. Production boot paths clear
    these env vars, so startup fails loud when a secret is missing.
    """
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("ASKPICKY_TEST_MODE")
    )


class Settings(BaseSettings):
    # --- external credentials
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    companies_house_api_key: str = ""

    # --- feature flags
    # Opt-in Managed Agents path for the company investigator. Default
    # off: with flag off, behaviour is byte-identical to the plain
    # company_scraper pipeline.
    enable_managed_company_investigator: bool = False
    enforce_rate_limit: bool = False
    # Per-agent Phase 1 timeout. Generous enough that Opus xhigh +
    # Playwright both fit comfortably; trim per-agent via future
    # config if needed.
    phase1_agent_timeout_s: float = 45.0
    # Tier 2 content-shield classifier timeout. For high-stakes
    # downstream agents, exceeding this becomes a REJECT (fail-closed).
    content_shield_tier2_timeout_s: float = 20.0
    # When True, verdict prompts treat a None Phase-1 output as
    # "API unreachable" (degrade confidence) rather than "no data".
    enable_source_status_verdict: bool = True
    # Prompt caching on large static system prompts + research bundles.
    enable_prompt_caching: bool = True
    # Route /api/queue/process through the Anthropic Batch API instead
    # of the in-process Semaphore fan-out. 50% cost discount + true
    # async semantics; up to ~1h end-to-end latency per batch.
    enable_batch_queue_runner: bool = False
    # Managed agentic Phase 4 generators. When True, the generator
    # routes through a `client.beta.sessions.*` session with live web
    # tools instead of the in-process single-call path. Off by default
    # — managed sessions are slower (~30-90s) and ~$0.30-1.50/call
    # more expensive but yield richer, live-grounded output. Each
    # falls back to its in-process equivalent on session failure.
    enable_managed_cover_letter: bool = False
    enable_managed_likely_questions: bool = False
    enable_managed_salary_strategist: bool = False

    # --- sponsor-register matching tunables (sub_agents/sponsor_register)
    sponsor_match_threshold: float = 92.0
    sponsor_ambiguous_band_low: float = 80.0
    sponsor_ambiguous_band_high: float = 95.0
    # Use the offline-trained Splink model at
    # `data/processed/sponsor_splink_model.json` to rescore
    # ambiguous-band candidates. Off by default — Splink is an
    # opt-in upgrade requiring an offline training pass.
    enable_splink_sponsor_match: bool = False
    # Pre-verdict triage (architecture gap #4). A Haiku call (~$0.02)
    # classifies forwards as SERIOUS/EXPLORATORY/DEFINITE_PASS before
    # the full Phase 1 pipeline. Only SERIOUS gets the full Opus verdict.
    # Single biggest cost-leverage move. Defaults on.
    enable_triage_before_verdict: bool = True

    # --- paths
    data_dir: Path = Path("./data")
    sqlite_db_path: Path = Path("./data/askpicky.db")
    faiss_index_path: Path = Path("./data/embeddings.faiss")
    generated_dir: Path = Path("./data/generated")  # CV/cover-letter files

    # --- credit budget
    credits_budget_usd: float = 500.0
    credits_warn_threshold_usd: float = 20.0

    # --- model defaults
    opus_model_id: str = "claude-opus-4-7"
    sonnet_model_id: str = "claude-sonnet-4-6"
    haiku_model_id: str = "claude-haiku-4-5-20251001"

    # --- embeddings
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = Field(default=384)

    # --- SMTP (notifications.channels.email_channel)
    # Optional. When SMTP_HOST + SMTP_FROM are unset the email channel
    # logs once and returns False — scheduler keeps draining.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # --- dual-surface identity (web + Telegram)
    # Single-user demo: both surfaces resolve to the same user_profiles
    # row. The Telegram adapter uses `update.effective_user.id` directly;
    # the web adapter reads demo_user_id since it has no auth. For
    # multi-user this becomes a session-derived identity in the web
    # layer. See docs/adr/0001-single-user-identity-seam.md.
    demo_user_id: str = ""
    api_port: int = 8000
    # CORS allowlist for the FastAPI app — strict, no wildcards.
    web_origin: str = "http://localhost:5173"
    # Public-facing URL the bot points un-onboarded users at.
    web_url: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def _require_secrets_in_prod(self) -> "Settings":
        """Fail fast at startup when required secrets are missing.

        Tests are exempted via PYTEST_CURRENT_TEST or ASKPICKY_TEST_MODE.
        In prod, an unset ANTHROPIC_API_KEY used to surface only on the
        first Opus call mid-pipeline — this raises at import time
        instead.
        """
        if _is_test_env():
            return self
        missing: list[str] = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.demo_user_id:
            missing.append("DEMO_USER_ID")
        if missing:
            raise ValueError(
                "Missing required environment variables: "
                + ", ".join(missing)
                + ". Set them in .env or export them before boot. "
                "Tests can skip this check with ASKPICKY_TEST_MODE=1."
            )
        return self


settings = Settings()
