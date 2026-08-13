"""Application settings.

Everything is overridable by environment variable with the ``YAFA_`` prefix,
e.g. ``YAFA_DATABASE_URL``. In production nothing here should need a code
change -- the container is configured entirely through the environment.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YAFA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "test", "prod"] = "dev"
    debug: bool = False

    # --- database ---------------------------------------------------------
    # asyncpg driver; alembic rewrites this to psycopg for its sync engine.
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://yafa:yafa@localhost:5432/yafa",
    )
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- auth -------------------------------------------------------------
    # No default. A service that boots with a well-known signing key is a
    # service whose tokens anyone can mint, so we refuse to start instead.
    # Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # --- cors -------------------------------------------------------------
    # Explicit origins only. Credentialed requests from "*" are rejected by
    # browsers anyway, so the old ["*"] + allow_credentials pairing was both
    # unsafe and broken.
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- qdrant -----------------------------------------------------------
    # A real service rather than the embedded local-mode client, which held a
    # single-process file lock and meant reseeding required stopping the API.
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "expense_categories"

    # --- redis ------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- models -----------------------------------------------------------
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_version: str = "all-MiniLM-L6-v2/knn-v1"
    categorize_top_k: int = 10
    categorize_confidence_threshold: float = 0.35

    whisper_model_size: str = "small.en"
    # "auto" resolves to cuda when torch reports a device, else cpu.
    whisper_device: Literal["auto", "cuda", "cpu"] = "auto"

    # --- llm fallback -----------------------------------------------------
    # Optional. Without a key the pipeline still works; it just loses the
    # structured-extraction fallback for transcripts the regex layer can't parse.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    llm_fallback_enabled: bool = True

    # --- telemetry --------------------------------------------------------
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4318"
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("jwt_secret")
    @classmethod
    def _reject_placeholder_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError(
                "YAFA_JWT_SECRET must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        return value

    @property
    def sync_database_url(self) -> str:
        """Alembic and the SQLite migration script need a blocking driver."""
        return str(self.database_url).replace("+asyncpg", "+psycopg")

    @property
    def llm_available(self) -> bool:
        return self.llm_fallback_enabled and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    """Cached so importing modules don't each re-read the environment."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
