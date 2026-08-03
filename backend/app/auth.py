"""Minimal API auth principals (admin/user) — not a full multi-tenant IAM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import AppUser, UserRole


@dataclass(frozen=True)
class Principal:
    """Resolved caller. Anonymous requests are treated as USER (read-only for standards)."""

    id: int | None
    username: str
    role: UserRole

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


async def get_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_api_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
    db: AsyncSession = Depends(get_db),
) -> Principal:
    token: str | None = None
    if x_api_token and x_api_token.strip():
        token = x_api_token.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token:
        return Principal(id=None, username="anonymous", role=UserRole.USER)

    # Prefer DB user rows when available; fall back to env bootstrap tokens.
    try:
        result = await db.execute(select(AppUser).where(AppUser.api_token == token))
        user = result.scalar_one_or_none()
    except Exception:  # noqa: BLE001 — missing table / DB not migrated yet
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        user = None

    if user is not None:
        return Principal(id=user.id, username=user.username, role=user.role)

    if token == settings.admin_api_token:
        return Principal(id=None, username="admin", role=UserRole.ADMIN)
    if token == settings.user_api_token:
        return Principal(id=None, username="user", role=UserRole.USER)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API token",
    )


async def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to upload or modify standards catalog",
        )
    return principal


async def require_authenticated(principal: Principal = Depends(get_principal)) -> Principal:
    """Any valid token (admin or user). Anonymous allowed for download if project-scoped? Keep open for MVP."""
    return principal
