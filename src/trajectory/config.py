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
        or os.environ.get("TRAJECTORY_TEST_MODE")
    )


class Settings(BaseSettings):
    # --- external credentials
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    companies_house_api_key: str = ""

    # --- feature flags
    # Opt-in Managed Agents path for the company investigator. Default
    # off: with flag off, Trajectory's behaviour is byte-identical to the
    # plain company_scraper pipeline. See src/trajectory/managed/.
    enable_managed_company_investigator: bool = False
    # Opt-in verdict ensemble: run verdict.generate twice in parallel
    # and take the conservative merge (NO_GO wins, union of blockers).
    # Doubles the per-verdict spend (~$1 → ~$2); intended for "money
    # no object" demo runs where hallucination resilience matters more
    # than cost. Default off; orchestrator falls through to single-call
    # path when unset. See orchestrator._ensemble_verdicts.
    enable_verdict_ensemble: bool = False
    enforce_rate_limit: bool = False
    # When a Phase 1 sub-agent exceeds this many seconds, its wrapper
    # catches `asyncio.TimeoutError` and returns the same conservative
    # fallback it returns on any other exception. Prevents a single
    # hung scrape from stalling the verdict pipeline. Default generous
    # enough that Opus xhigh + Playwright both fit comfortably; trim
    # on a per-agent basis via future config if needed.
    phase1_agent_timeout_s: float = 45.0
    # When the Tier 2 content-shield classifier doesn't respond within
    # this window, the shield treats it as a persistent failure. For
    # high-stakes downstream agents, that becomes a REJECT (fail-closed).
    content_shield_tier2_timeout_s: float = 20.0
    # When True, verdict prompts and downstream agents treat a None
    # Phase-1 output as potentially "API unreachable" rather than
    # definitely "no data". Flip to False to revert to the pre-A6
    # behaviour (treat missing = no data). See schemas.SourceStatus.
    enable_source_status_verdict: bool = True
    # Prompt caching breakpoints on large static system prompts and
    # research bundles. Additive on the API side, but gated so a
    # misbehaving SDK version can be cut over quickly.
    enable_prompt_caching: bool = True
    # Opt-in 1-hour cache TTL (vs default 5m). Useful for batch-runner
    # system prompts and bot per-user prefixes that span hours. Costs
    # slightly more on cache write (~2x of 5m) but pays off when the
    # same prefix is reused after the 5m window expires.
    enable_1hr_cache_for_batch: bool = False
    # Opt-in: route /api/queue/process through the Anthropic Batch API
    # instead of the in-process asyncio.Semaphore fan-out. 50% cost
    # discount + true async semantics; trade-off is up to ~1h end-to-end
    # latency per batch. Off by default; flips on for offline overnight
    # processing. PROCESS Entry 43, Workstream E.
    enable_batch_queue_runner: bool = False
    # Use the Managed Agents reviews_investigator session instead of the
    # no-op jobspy `sub_agents/reviews.py` path. PROCESS Entry 43,
    # Workstream C. Falls back to the legacy path on session failure
    # (graceful degradation — Phase 1 never aborts on reviews).
    enable_managed_reviews_investigator: bool = False
    # When `enable_verdict_ensemble=True`, the second of the two parallel
    # verdict runs uses `managed/verdict_deep_research.py` (Web Search +
    # Web Fetch) instead of the standard `verdict_agent.generate`. Off
    # by default — symmetric ensemble keeps the existing behaviour.
    # PROCESS Entry 43, Workstream D.
    enable_verdict_ensemble_deep_research: bool = False
    # Bot conversation surface — opt-in Compaction + Context editing.
    # Compaction summarises old turns server-side once context approaches
    # the window; context editing prunes tool-result blocks. Both
    # eliminate the "drop everything but CareerEntry" workaround in the
    # current bot persistence path. Off by default while we verify the
    # behaviour against multi-day Telegram threads. PROCESS Entry 43,
    # Workstream H.
    enable_bot_compaction: bool = False
    enable_bot_context_editing: bool = False
    # Route draft_cv through the `cv_tailor_advisor` Managed Agents
    # session (Sonnet executor + Opus advisor via the Advisor tool)
    # instead of the in-process `cv_tailor_agentic` multi-turn loop.
    # Both paths run the agentic FAISS-retrieval implementation — the
    # legacy single-call path was retired in PROCESS Entry 42 (D5).
    # The flag exists so the Advisor-tool surface can be flipped on
    # per-deploy once it's wired (CLAUDE.md "Wiring status"); default
    # off matches the project's "managed agents are opt-in" pattern
    # (`enable_managed_company_investigator`, `enable_verdict_ensemble`).
    enable_managed_cv_tailor: bool = False

    # --- paths
    data_dir: Path = Path("./data")
    sqlite_db_path: Path = Path("./data/trajectory.db")
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

    # --- dual-surface (web + Telegram). MIGRATION_PLAN.md.
    # Single-user demo: both surfaces resolve to the same user_profiles
    # row. The Telegram adapter uses `update.effective_user.id` directly
    # (which equals demo_user_id since you're the only user); the web
    # adapter reads demo_user_id since it has no auth. For multi-user
    # this becomes a session-derived identity in the web layer.
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

        Tests are exempted via PYTEST_CURRENT_TEST or TRAJECTORY_TEST_MODE
        (see _is_test_env). In prod, an unset ANTHROPIC_API_KEY used to
        surface only on the first Opus call mid-pipeline — this raises
        at import time instead.
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
                "Tests can skip this check with TRAJECTORY_TEST_MODE=1."
            )
        return self


settings = Settings()
