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
    from sqlalchemy import text

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] create_all warning: {exc}")

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
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] alter warning: {exc}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
