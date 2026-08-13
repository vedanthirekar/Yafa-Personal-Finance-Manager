from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YAFA_", env_file=".env", extra="ignore")

    # Swappable via DATABASE_URL/YAFA_DATABASE_URL alone -- no code changes needed
    # to move from local SQLite (dev/demo) to Postgres (concurrent-write production use).
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'yafa.db').as_posix()}"

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    qdrant_path: str = str(BACKEND_DIR / "qdrant_data")
    qdrant_collection: str = "expense_categories"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    categorize_top_k: int = 10
    categorize_confidence_threshold: float = 0.35

    # "base.en" balances speed/accuracy on CPU; bump to "small.en" for
    # noticeably better accuracy at ~2-3x the inference time.
    whisper_model_size: str = "base.en"

    cors_origins: list[str] = ["*"]


settings = Settings()
