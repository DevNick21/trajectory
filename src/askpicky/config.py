"""Runtime configuration — single source of truth for env vars and paths.

Everything that reads `.env` or hardcoded paths goes through `settings`. Do
not read `os.environ` directly elsewhere in the codebase.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

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

    # Multi-provider support (architecture gap #10)
    # DeepSeek — OpenAI-compatible endpoint at api.deepseek.com/v1
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    # Firecrawl — anti-bot page scraping fallback
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev/v2"
    # OpenAI — GPT-5.4 for primary verdict, benchmarking, and optional routing
    openai_api_key: str = ""

    # --- feature flags
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
    # the full Phase 1 pipeline. Only SERIOUS gets the full verdict.
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
    # DeepSeek models (Anthropic-compatible endpoint)
    deepseek_flash_model_id: str = "deepseek-v4-flash"
    deepseek_pro_model_id: str = "deepseek-v4-pro"
    # OpenAI models
    openai_mini_model_id: str = "gpt-5.4-mini"
    openai_pro_model_id: str = "gpt-5.4"
    # LangGraph orchestrator (opt-in — wraps handle_forward_job)
    enable_langgraph_orchestrator: bool = False

    # Per-agent model routing. Keys are agent_name strings; overrides
    # the default (opus_model_id) when set. Use DeepSeek V4 Flash for
    # low-stakes extraction/routing tasks.
    # DeepSeek Pro handles self-audit and voice-sensitive generators.
    # Verdict is NOT in the map — the sub-agent wrapper passes the model
    # explicitly (GPT-5.4 primary, DeepSeek Pro fallback on failure).
    # provider is "anthropic", "deepseek", or "openai". Default: "anthropic".
    # Example: {"jd_extractor": ("deepseek-v4-flash", "deepseek")}
    #
    # Verdict is NOT in the map — the sub-agent wrapper passes the model
    # explicitly (GPT-5.4 primary, DeepSeek Pro fallback on failure).
    agent_model_map: dict = Field(default_factory=lambda: {
        "self_audit": ("deepseek-v4-pro", "deepseek"),
        "cover_letter": ("deepseek-v4-pro", "deepseek"),
        "cv_tailor": ("deepseek-v4-pro", "deepseek"),
        "salary_strategist": ("deepseek-v4-pro", "deepseek"),
        # DeepSeek V4 Flash — low-stakes extraction/routing ($0.14/$0.28 per Mtok)
        "intent_router": ("deepseek-v4-flash", "deepseek"),
        "triage": ("deepseek-v4-flash", "deepseek"),
        "jd_extractor": ("deepseek-v4-flash", "deepseek"),
        "company_scraper_summariser": ("deepseek-v4-flash", "deepseek"),
        "red_flags": ("deepseek-v4-flash", "deepseek"),
        "ghost_job_jd_scorer": ("deepseek-v4-flash", "deepseek"),
        "interview_questions": ("deepseek-v4-flash", "deepseek"),
        "star_polisher": ("deepseek-v4-flash", "deepseek"),
        "style_extractor": ("deepseek-v4-flash", "deepseek"),
        "onboarding_parser": ("deepseek-v4-flash", "deepseek"),
        "cv_parser": ("deepseek-v4-flash", "deepseek"),
        "draft_reply": ("deepseek-v4-flash", "deepseek"),
        "content_shield_tier2": ("deepseek-v4-flash", "deepseek"),
    })

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
        # DeepSeek is the default for most agents — warn if missing
        if not self.deepseek_api_key:
            import warnings
            warnings.warn(
                "DEEPSEEK_API_KEY is not set — agents routed to DeepSeek "
                "will fall back to Anthropic (significantly more expensive). "
                "Set DEEPSEEK_API_KEY in .env to enable DeepSeek V4 Flash.",
                RuntimeWarning,
                stacklevel=2,
            )
        return self


settings = Settings()
