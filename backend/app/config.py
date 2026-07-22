from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent


def _normalize_database_url(url: str) -> str:
    """Accept Supabase/Postgres URLs and make them async-SQLAlchemy friendly."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # Supabase requires SSL; asyncpg expects ssl=require in the query string.
    if "supabase.co" in url and "ssl=" not in url:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}ssl=require"
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TenderRisk Analyzer"
    api_prefix: str = "/api"
    database_url: str = f"sqlite+aiosqlite:///{(_BASE_DIR / 'tenderrisk.db').as_posix()}"
    storage_dir: Path = _BASE_DIR / "storage"
    # 0 = بدون سقف حجم (فقط محدودیت فضای دیسک سیستم)
    max_upload_mb: int = 0
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Supabase (optional — when set, files go to Storage)
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_bucket: str = "project-documents"

    @field_validator("database_url", mode="before")
    @classmethod
    def _db_url(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip():
            return _normalize_database_url(value.strip())
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                return value
            return [part.strip() for part in raw.split(",") if part.strip()]
        return value

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
