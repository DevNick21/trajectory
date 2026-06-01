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
    companies_house_api_key: str = ""

    # DeepSeek — primary LLM provider (OpenAI-compatible endpoint)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    # OpenAI — GPT-5.4 for verdict, benchmarking, and optional routing
    openai_api_key: str = ""
    # Backward-compatible aliases used by legacy tests/smokes while the
    # runtime routes through TIER_* and agent_tier_map.
    anthropic_api_key: str = ""
    openai_pro_model_id: str = "gpt-5.4"
    deepseek_pro_model_id: str = "deepseek-v4-pro"
    opus_model_id: str = "gpt-5.4"
    sonnet_model_id: str = "deepseek-v4-flash"
    # Firecrawl — anti-bot page scraping fallback
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev/v2"

    # --- three-tier model config
    # Each tier is a (model_id, provider) tuple. Change one line to
    # swap every agent in that tier. provider is "deepseek" or "openai".
    TIER_FAST: tuple[str, str] = ("deepseek-v4-flash", "deepseek")
    TIER_NORMAL: tuple[str, str] = ("deepseek-v4-pro", "deepseek")
    TIER_STRONG: tuple[str, str] = ("gpt-5.4", "openai")

    # Per-agent tier routing. Keys are agent_name strings; values are
    # "fast", "normal", or "strong". Unknown agents default to "normal".
    agent_tier_map: dict = Field(default_factory=lambda: {
        # fast tier — low-stakes extraction / routing / triage
        "intent_router": "fast",
        "triage": "fast",
        "jd_extractor": "fast",
        "company_scraper_summariser": "fast",
        "red_flags": "fast",
        "ghost_job_jd_scorer": "fast",
        "interview_questions": "fast",
        "star_polisher": "fast",
        "style_extractor": "fast",
        "onboarding_parser": "fast",
        "cv_parser": "fast",
        "draft_reply": "fast",
        "content_shield_tier2": "fast",
        "memory_extractor": "fast",
        # normal tier — quality-sensitive generation
        "cover_letter": "normal",
        "cv_tailor": "normal",
        "cv_tailor_agentic": "normal",
        "salary_strategist": "normal",
        "application_answer_shaper": "normal",
        # strong tier — high-stakes judgment
        "verdict": "strong",
        "self_audit": "strong",
        "offer_analyst": "strong",
    })

    # --- feature flags
    # Per-agent Phase 1 timeout.
    phase1_agent_timeout_s: float = 45.0
    # Tier 2 content-shield classifier timeout.
    content_shield_tier2_timeout_s: float = 20.0
    # When True, verdict prompts treat a None Phase-1 output as
    # "API unreachable" (degrade confidence) rather than "no data".
    enable_source_status_verdict: bool = True
    # Prompt caching on large static system prompts + research bundles.
    enable_prompt_caching: bool = True

    # --- sponsor-register matching tunables
    sponsor_match_threshold: float = 92.0
    sponsor_ambiguous_band_low: float = 80.0
    sponsor_ambiguous_band_high: float = 95.0
    enable_splink_sponsor_match: bool = False
    # Pre-verdict triage
    enable_triage_before_verdict: bool = True
    enable_managed_company_investigator: bool = False
    enable_batch_queue_runner: bool = False

    # --- paths
    data_dir: Path = Path("./data")
    sqlite_db_path: Path = Path("./data/askpicky.db")
    faiss_index_path: Path = Path("./data/embeddings.faiss")
    generated_dir: Path = Path("./data/generated")

    # --- credit budget
    credits_budget_usd: float = 500.0
    credits_warn_threshold_usd: float = 20.0
    # Keep disabled by default for local/dev parity; hosted deployments
    # should set ASKPICKY_ENFORCE_RATE_LIMIT=true until auth-backed quotas land.
    enforce_rate_limit: bool = False

    # --- embeddings
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = Field(default=384)

    # --- SMTP (notifications.channels.email_channel)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # --- web surface identity
    demo_user_id: str = ""
    api_port: int = 8000
    web_origin: str = "http://localhost:5173"
    web_url: str = "http://localhost:5173"

    # LangGraph orchestrator (opt-in)
    enable_langgraph_orchestrator: bool = False
    # Application-assist background memory extraction. The deterministic
    # extractor runs immediately; this opt-in flag controls whether the
    # richer LLM extractor runs after approval so hosted deployments can
    # budget it explicitly.
    enable_memory_extractor_llm: bool = False

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
        """
        if _is_test_env():
            return self
        missing: list[str] = []
        if not self.deepseek_api_key:
            missing.append("DEEPSEEK_API_KEY")
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
