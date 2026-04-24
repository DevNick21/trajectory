"""Runtime configuration — single source of truth for env vars and paths.

Everything that reads `.env` or hardcoded paths goes through `settings`. Do
not read `os.environ` directly elsewhere in the codebase.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Opt-in agentic CV tailor (multi-turn FAISS retrieval). Default off:
    # legacy single-call path stays in production until A/B validation
    # confirms quality parity. See `sub_agents/cv_tailor_agentic.py`.
    enable_agentic_cv_tailor: bool = False
    enforce_rate_limit: bool = False

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


settings = Settings()
