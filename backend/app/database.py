from collections.abc import AsyncGenerator
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    url = settings.database_url
    is_postgres = "postgresql" in url
    if is_postgres:
        # Disable SQLAlchemy asyncpg dialect prepared-statement cache (PgBouncer-safe).
        join = "&" if "?" in url else "?"
        if "prepared_statement_cache_size=" not in url:
            url = f"{url}{join}prepared_statement_cache_size=0"
        return create_async_engine(
            url,
            echo=False,
            poolclass=NullPool,
            connect_args={
                # Disable asyncpg's own statement cache for transaction-mode PgBouncer.
                "statement_cache_size": 0,
                "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4().hex}__",
            },
        )
    return create_async_engine(url, echo=False)


engine = _build_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    # Import models so metadata is registered before create_all.
    from app import models  # noqa: F401
    from sqlalchemy import select, text

    from app.config import settings
    from app.models import AppUser, UserRole

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] create_all warning: {exc}")

    # Ensure standards-catalog tables exist even if create_all was skipped earlier.
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS app_users (
                      id bigserial primary key,
                      username varchar(128) not null unique,
                      role varchar(16) not null default 'user',
                      api_token varchar(128) not null unique,
                      created_at timestamptz not null default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_standard_assets (
                      id bigserial primary key,
                      standard_code varchar(64) not null unique,
                      title varchar(512) not null,
                      title_fa varchar(512),
                      title_en varchar(512),
                      title_de varchar(512),
                      publisher varchar(255),
                      standard_class varchar(32) not null default 'technical',
                      original_name varchar(512) not null,
                      stored_path varchar(1024) not null,
                      content_type varchar(255),
                      size_bytes integer not null default 0,
                      uploaded_by varchar(128),
                      created_at timestamptz not null default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS project_standards (
                      id bigserial primary key,
                      project_id bigint not null references projects(id) on delete cascade,
                      standard_code varchar(64) not null,
                      is_selected boolean not null default true,
                      selected_by varchar(32) not null default 'system_default',
                      applicability_level varchar(32),
                      standard_class varchar(32),
                      title varchar(512),
                      created_at timestamptz not null default now(),
                      unique (project_id, standard_code)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS experience_knowledge_items (
                      id bigserial primary key,
                      experience_id varchar(128) not null unique,
                      title varchar(512) not null,
                      description text not null default '',
                      category varchar(64) not null default 'lesson',
                      origin_kind varchar(64) not null default 'admin_curated',
                      source varchar(512),
                      author varchar(255),
                      validation_status varchar(64) not null default 'validated',
                      confidence_level varchar(32) not null default 'medium',
                      related_risk_id varchar(128),
                      related_risk_category varchar(64),
                      related_project_types_json text,
                      recommended_prevention text,
                      related_documents_json text,
                      related_outcomes_json text,
                      match_keywords_json text,
                      version integer not null default 1,
                      is_active boolean not null default true,
                      created_at timestamptz not null default now(),
                      updated_at timestamptz not null default now()
                    )
                    """
                )
            )
    except Exception as exc:  # noqa: BLE001
        # SQLite uses different DDL; create_all above already covers local DBs.
        print(f"[init_db] standards tables ensure warning: {exc}")

    # Additive columns for existing MVP Postgres databases (must not block boot).
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE projects "
                    "ADD COLUMN IF NOT EXISTS project_type VARCHAR(64) DEFAULT 'infrastructure'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE projects "
                    "ADD COLUMN IF NOT EXISTS country_profile_code VARCHAR(64)"
                )
            )
            await conn.execute(
                text(
                    "UPDATE projects SET project_type = 'infrastructure' "
                    "WHERE project_type IS NULL"
                )
            )
            for stmt in (
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS finding_category VARCHAR(32) DEFAULT 'risk'",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS risk_score INTEGER",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_excerpt TEXT",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS cause_effect_json TEXT",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS data_completeness_caveat TEXT",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS estimated_impact VARCHAR(512)",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_layer VARCHAR(32)",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS confidence_score INTEGER",
                "ALTER TABLE experience_knowledge_items ADD COLUMN IF NOT EXISTS match_keywords_json TEXT",
            ):
                try:
                    await conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] alter warning: {exc}")

    # Seed minimal admin/user principals for Phase 0 standards access control.
    try:
        async with SessionLocal() as session:
            for username, role, token in (
                ("admin", UserRole.ADMIN, settings.admin_api_token),
                ("user", UserRole.USER, settings.user_api_token),
            ):
                existing = (
                    await session.execute(select(AppUser).where(AppUser.username == username))
                ).scalar_one_or_none()
                if existing is None:
                    session.add(AppUser(username=username, role=role, api_token=token))
                else:
                    existing.role = role
                    existing.api_token = token
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] app_users seed warning: {exc}")

    # Phase 6 — seed Risk Knowledge Base (46 Risk IDs from Batches 1–2). Additive upsert.
    try:
        from app.knowledge.rkb import seed_risks_table

        async with SessionLocal() as session:
            stats = await seed_risks_table(session)
            print(
                f"[init_db] RKB seed: inserted={stats['inserted']} "
                f"table_count={stats['table_count']} unique_seed={stats['unique_seed_ids']}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] risks seed warning: {exc}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
