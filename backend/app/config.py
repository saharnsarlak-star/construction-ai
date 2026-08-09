from pathlib import Path
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    # Railway sets CORS_ORIGINS as comma-separated text — do not JSON-decode it.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Supabase (optional — when set, files go to Storage)
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_bucket: str = "project-documents"
    # Local/dev: ignore Supabase credentials and write uploads to disk
    force_local_storage: bool = False

    # Phase 0 minimal auth tokens (bootstrap; also seeded into app_users)
    admin_api_token: str = "dev-admin-token"
    user_api_token: str = "dev-user-token"
    admin_email: str = "admin@tenderrisk.local"
    admin_password: str = "Admin123!"
    user_email: str = "user@tenderrisk.local"
    user_password: str = "User123!"

    # Phase 1 — Canonical Document Model writer (default OFF = production-safe)
    cdm_enabled: bool = False

    # Phase 2 — Party / Element Registry / OntologyEdge (default OFF)
    ontology_enabled: bool = False

    # Phase 3 — PYTHON seed rule runners (default OFF; keyword analyzer remains default)
    new_rule_engine_enabled: bool = False

    # Phase 4 — AI / HYBRID seed runners (default OFF)
    # No provider was previously configured; OpenAI-compatible Chat Completions via httpx.
    ai_rule_engine_enabled: bool = False
    openai_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_provider: str = "openai_compatible"  # openai_compatible | replay
    llm_replay_path: str | None = None
    ai_max_calls_per_analysis: int = 12

    # Phase 5 — Knowledge Graph risk chains (default OFF)
    knowledge_graph_enabled: bool = False

    # Phase 6 — Risk Knowledge Base in DB (default OFF; fallback to Python seed dicts)
    rkb_db_enabled: bool = False

    # Phase 7 — Human Construction Experience Knowledge layer (default OFF)
    experience_layer_enabled: bool = False

    # Phase 8 — Vision drawing checks + GAEB 90 fixed-width (default OFF)
    vision_drawing_checks_enabled: bool = False
    gaeb90_enabled: bool = False
    vision_llm_model: str = "gpt-4o-mini"
    vision_max_pages_per_doc: int = 2

    @field_validator(
        "cdm_enabled",
        "ontology_enabled",
        "new_rule_engine_enabled",
        "ai_rule_engine_enabled",
        "knowledge_graph_enabled",
        "rkb_db_enabled",
        "experience_layer_enabled",
        "vision_drawing_checks_enabled",
        "gaeb90_enabled",
        mode="before",
    )
    @classmethod
    def _bool_flag(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value

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
                import json

                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(part).strip() for part in parsed if str(part).strip()]
                except json.JSONDecodeError:
                    pass
            return [part.strip() for part in raw.split(",") if part.strip()]
        return value

    # Demo workspace limits (applied to approved demo accounts)
    demo_days_valid: int = 7
    demo_max_documents: int = 5
    demo_max_analyses: int = 2
    demo_max_file_mb: int = 20
    demo_max_total_mb: int = 50

    @property
    def supabase_enabled(self) -> bool:
        if self.force_local_storage:
            return False
        return bool(self.supabase_url and self.supabase_service_role_key)


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
