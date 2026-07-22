from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import projects
from app.schemas import HealthOut
from app.services.storage import storage_mode


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects.router, prefix=settings.api_prefix)


@app.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok", app=settings.app_name)


@app.get("/api/health/detail")
async def health_detail() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "storage": storage_mode(),
        "database": "postgres" if "postgresql" in settings.database_url else "sqlite",
    }
