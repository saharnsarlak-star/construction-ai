from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.startup_checks import run_startup_checks
from app.routers import auth, experience, implementation_steps, project_registry, projects, risks, standards, taxonomy
from app.schemas import HealthOut
from app.services.storage import storage_mode


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    run_startup_checks()
    await init_db()
    from app.tender_taxonomy import warm_taxonomy_cache

    warm_taxonomy_cache()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(standards.router, prefix=settings.api_prefix)
app.include_router(risks.router, prefix=settings.api_prefix)
app.include_router(experience.router, prefix=settings.api_prefix)
app.include_router(implementation_steps.router, prefix=settings.api_prefix)
app.include_router(project_registry.router, prefix=settings.api_prefix)
app.include_router(taxonomy.router, prefix=settings.api_prefix)


@app.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok", app=settings.app_name)


@app.get("/api/health/detail")
async def health_detail() -> dict:
    from app.services.extractor import ocr_status

    return {
        "status": "ok",
        "app": settings.app_name,
        "storage": storage_mode(),
        "database": "postgres" if "postgresql" in settings.database_url else "sqlite",
        "ocr": ocr_status(),
    }


@app.get("/api/health/db")
async def health_db() -> dict:
    """Diagnose projects table columns (for Railway/Supabase schema drift)."""
    from sqlalchemy import text

    from app.database import SessionLocal

    try:
        async with SessionLocal() as session:
            cols = (
                await session.execute(
                    text(
                        """
                        select column_name, data_type
                        from information_schema.columns
                        where table_schema = 'public' and table_name = 'projects'
                        order by ordinal_position
                        """
                    )
                )
            ).all()
            count = (await session.execute(text("select count(*) from projects"))).scalar()
        return {
            "status": "ok",
            "projects_count": count,
            "columns": [{"name": c[0], "type": c[1]} for c in cols],
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
