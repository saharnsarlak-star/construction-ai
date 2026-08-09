"""Demo account quotas, expiry, and feature locks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AppUser, Document, Project


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_demo_user(user: AppUser | None) -> bool:
    if user is None:
        return False
    if getattr(user, "is_demo_user", False):
        return True
    return bool(getattr(user, "demo_project_id", None))


def demo_expired(user: AppUser) -> bool:
    expires = _aware(getattr(user, "demo_expires_at", None))
    if expires is None:
        return False
    return _utcnow() >= expires


def days_left(user: AppUser) -> int | None:
    expires = _aware(getattr(user, "demo_expires_at", None))
    if expires is None:
        return None
    delta = expires - _utcnow()
    return max(0, int(delta.total_seconds() // 86400))


def set_demo_window(user: AppUser) -> None:
    user.is_demo_user = True
    user.demo_expires_at = _utcnow() + timedelta(days=max(1, settings.demo_days_valid))
    if getattr(user, "demo_analyses_used", None) is None:
        user.demo_analyses_used = 0


async def _doc_stats(db: AsyncSession, project_id: int) -> tuple[int, int]:
    count = (
        await db.execute(select(func.count()).select_from(Document).where(Document.project_id == project_id))
    ).scalar_one()
    total = (
        await db.execute(select(func.coalesce(func.sum(Document.size_bytes), 0)).where(Document.project_id == project_id))
    ).scalar_one()
    return int(count or 0), int(total or 0)


async def build_demo_limits(db: AsyncSession, user: AppUser | None) -> dict:
    if not is_demo_user(user) or user is None:
        return {
            "is_demo": False,
            "expires_at": None,
            "expired": False,
            "days_left": None,
            "max_documents": 0,
            "documents_used": 0,
            "documents_remaining": 0,
            "max_analyses": 0,
            "analyses_used": 0,
            "analyses_remaining": 0,
            "max_file_mb": 0,
            "max_total_mb": 0,
            "can_create_project": True,
            "can_upload": True,
            "can_analyze": True,
            "locks": [],
        }

    docs_used = 0
    total_bytes = 0
    if user.demo_project_id:
        docs_used, total_bytes = await _doc_stats(db, user.demo_project_id)

    analyses_used = int(getattr(user, "demo_analyses_used", 0) or 0)
    expired = demo_expired(user)
    docs_remaining = max(0, settings.demo_max_documents - docs_used)
    analyses_remaining = max(0, settings.demo_max_analyses - analyses_used)
    locks: list[str] = [
        "extra_projects",
        "experience_admin",
        "catalog_upload",
    ]
    if expired:
        locks.extend(["upload", "analyze", "expired"])

    return {
        "is_demo": True,
        "expires_at": _aware(user.demo_expires_at),
        "expired": expired,
        "days_left": days_left(user),
        "max_documents": settings.demo_max_documents,
        "documents_used": docs_used,
        "documents_remaining": 0 if expired else docs_remaining,
        "max_analyses": settings.demo_max_analyses,
        "analyses_used": analyses_used,
        "analyses_remaining": 0 if expired else analyses_remaining,
        "max_file_mb": settings.demo_max_file_mb,
        "max_total_mb": settings.demo_max_total_mb,
        "can_create_project": False,
        "can_upload": (not expired) and docs_remaining > 0,
        "can_analyze": (not expired) and analyses_remaining > 0,
        "locks": locks,
        "total_bytes_used": total_bytes,
    }


async def require_demo_active(db: AsyncSession, user: AppUser | None) -> None:
    if not is_demo_user(user) or user is None:
        return
    if demo_expired(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo expired. Contact us to upgrade.",
        )


async def assert_can_create_project(db: AsyncSession, user: AppUser | None) -> None:
    if is_demo_user(user):
        await require_demo_active(db, user)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo accounts cannot create extra projects",
        )


async def assert_can_upload(
    db: AsyncSession,
    user: AppUser | None,
    project: Project,
    *,
    incoming_files: int,
    incoming_bytes: int,
) -> None:
    if not project.is_demo and not is_demo_user(user):
        return
    if user is None:
        raise HTTPException(status_code=403, detail="Authentication required for demo upload")
    await require_demo_active(db, user)
    if user.demo_project_id and project.id != user.demo_project_id:
        raise HTTPException(status_code=403, detail="Demo users may only use their demo project")

    docs_used, total_bytes = await _doc_stats(db, project.id)
    if docs_used + incoming_files > settings.demo_max_documents:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Demo limit: max {settings.demo_max_documents} documents "
                f"({docs_used} already used)"
            ),
        )
    max_file = settings.demo_max_file_mb * 1024 * 1024
    if incoming_bytes > max_file and incoming_files == 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Demo limit: each file must be ≤ {settings.demo_max_file_mb} MB",
        )
    max_total = settings.demo_max_total_mb * 1024 * 1024
    if total_bytes + incoming_bytes > max_total:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Demo limit: total upload size ≤ {settings.demo_max_total_mb} MB",
        )


async def assert_can_analyze(db: AsyncSession, user: AppUser | None, project: Project) -> AppUser | None:
    if not project.is_demo and not is_demo_user(user):
        return user
    if user is None:
        # Load owner for demo project
        if project.owner_user_id:
            user = await db.get(AppUser, project.owner_user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="Authentication required for demo analysis")
    await require_demo_active(db, user)
    used = int(getattr(user, "demo_analyses_used", 0) or 0)
    if used >= settings.demo_max_analyses:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Demo limit: max {settings.demo_max_analyses} analyses",
        )
    return user


async def record_demo_analysis(db: AsyncSession, user: AppUser | None) -> None:
    if user is None or not is_demo_user(user):
        return
    user.demo_analyses_used = int(getattr(user, "demo_analyses_used", 0) or 0) + 1
    await db.commit()
