from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    # Import models so metadata is registered before create_all.
    from app import models  # noqa: F401
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Additive columns for existing MVP Postgres/SQLite databases.
        dialect = conn.engine.dialect.name
        alters = [
            ("project_type", "VARCHAR(64) DEFAULT 'infrastructure'"),
            ("country_profile_code", "VARCHAR(64)"),
        ]
        for col, coltype in alters:
            try:
                if dialect == "sqlite":
                    await conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col} {coltype}"))
                else:
                    await conn.execute(
                        text(f"ALTER TABLE projects ADD COLUMN IF NOT EXISTS {col} {coltype}")
                    )
            except Exception:
                # Column already exists or table uses a different shape.
                pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
