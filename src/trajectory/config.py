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
    rapidapi_key: str = ""

    # --- feature flags
    use_managed_agents: bool = True
    enforce_rate_limit: bool = False

    # --- paths
    data_dir: Path = Path("./data")
    sqlite_db_path: Path = Path("./data/trajectory.db")
    faiss_index_path: Path = Path("./data/embeddings.faiss")

    # --- credit budget
    credits_budget_usd: float = 500.0
    credits_warn_threshold_usd: float = 20.0

    # --- model defaults
    opus_model_id: str = "claude-opus-4-7"
    sonnet_model_id: str = "claude-sonnet-4-6"
    haiku_model_id: str = "claude-haiku-4-5-20251001"

    # --- Managed Agents beta
    managed_agents_beta_header: str = "managed-agents-2026-04-01"

    # --- embeddings
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = Field(default=384)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()
