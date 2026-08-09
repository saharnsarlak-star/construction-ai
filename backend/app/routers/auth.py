"""Email/password login, demo registration, and admin approval."""

from __future__ import annotations

import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, get_principal, require_admin
from app.config import settings
from app.database import get_db
from app.models import AccountStatus, AppUser, CountryCode, LanguageCode, Project, ProjectType, UserRole
from app.schemas import (
    AuthMeOut,
    DemoLimitsOut,
    DemoRequestActionOut,
    DemoRequestDeleteIn,
    DemoRequestDeleteOut,
    DemoRequestIn,
    DemoRequestOut,
    LoginIn,
    LoginOut,
)
from app.knowledge.country_profiles import get_country_profile
from app.services.demo_limits import build_demo_limits, is_demo_user, set_demo_window
from app.services.passwords import hash_password, verify_password
from app.services.project_standards import ensure_project_standards

router = APIRouter(tags=["auth"])


def _account_status(user: AppUser) -> str:
    raw = (getattr(user, "status", None) or AccountStatus.APPROVED.value).strip().lower()
    if raw in {AccountStatus.PENDING.value, AccountStatus.APPROVED.value, AccountStatus.REJECTED.value}:
        return raw
    return AccountStatus.APPROVED.value


def _username_from_email(email: str) -> str:
    local = email.split("@", 1)[0].strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", local).strip("-._") or "user"
    return cleaned[:80]


def _demo_out(user: AppUser) -> DemoRequestOut:
    return DemoRequestOut(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        company=user.company,
        phone=user.phone,
        message=user.message,
        status=_account_status(user),  # type: ignore[arg-type]
        demo_project_id=user.demo_project_id,
        created_at=user.created_at,
    )


@router.get("/auth/me", response_model=AuthMeOut)
async def auth_me(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> AuthMeOut:
    if principal.id is None and principal.username == "anonymous":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    status_value = AccountStatus.APPROVED.value
    demo_project_id = None
    demo: DemoLimitsOut | None = None
    if principal.id is not None:
        user = await db.get(AppUser, principal.id)
        if user is not None:
            status_value = _account_status(user)
            demo_project_id = user.demo_project_id
            demo = DemoLimitsOut(**(await build_demo_limits(db, user)))
    return AuthMeOut(
        username=principal.username,
        role=principal.role.value,  # type: ignore[arg-type]
        is_admin=principal.is_admin,
        status=status_value,  # type: ignore[arg-type]
        demo_project_id=demo_project_id,
        demo=demo,
    )


@router.post("/auth/login", response_model=LoginOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)) -> LoginOut:
    email = body.email.strip().lower()
    if not email or not body.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    result = await db.execute(select(AppUser).where(AppUser.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    acct = _account_status(user)
    if acct == AccountStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo request is pending admin approval",
        )
    if acct == AccountStatus.REJECTED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo request was rejected",
        )

    if is_demo_user(user) and not getattr(user, "demo_expires_at", None):
        set_demo_window(user)
        await db.commit()
        await db.refresh(user)

    demo = DemoLimitsOut(**(await build_demo_limits(db, user)))
    return LoginOut(
        api_token=user.api_token,
        username=user.username,
        role=user.role.value,  # type: ignore[arg-type]
        is_admin=user.role.value == "admin",
        status=acct,  # type: ignore[arg-type]
        demo_project_id=user.demo_project_id,
        demo=demo,
    )


@router.post("/auth/demo-request", response_model=DemoRequestOut, status_code=status.HTTP_201_CREATED)
async def create_demo_request(body: DemoRequestIn, db: AsyncSession = Depends(get_db)) -> DemoRequestOut:
    email = body.email.strip().lower()
    full_name = body.full_name.strip()
    if "@" not in email or "." not in email.split("@", 1)[-1]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email")
    if len(body.password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")

    existing = await db.execute(
        select(AppUser).where(or_(AppUser.email == email, AppUser.username == _username_from_email(email)))
    )
    collision = existing.scalar_one_or_none()
    if collision is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    base = _username_from_email(email)
    username = base
    for _ in range(6):
        taken = await db.execute(select(AppUser.id).where(AppUser.username == username))
        if taken.scalar_one_or_none() is None:
            break
        username = f"{base}-{secrets.token_hex(2)}"

    user = AppUser(
        username=username,
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.USER,
        status=AccountStatus.PENDING.value,
        full_name=full_name,
        company=(body.company or "").strip() or None,
        phone=(body.phone or "").strip() or None,
        message=(body.message or "").strip() or None,
        is_demo_user=True,
        api_token=f"demo-{uuid4().hex}",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _demo_out(user)


@router.get("/auth/demo-requests", response_model=list[DemoRequestOut])
async def list_demo_requests(
    _: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[DemoRequestOut]:
    result = await db.execute(
        select(AppUser)
        .where(
            or_(
                AppUser.status == AccountStatus.PENDING.value,
                AppUser.status == AccountStatus.APPROVED.value,
                AppUser.status == AccountStatus.REJECTED.value,
            ),
            AppUser.role == UserRole.USER,
            AppUser.email.is_not(None),
        )
        .order_by(AppUser.id.desc())
    )
    # Prefer showing pending first, then recent others that came via demo form (have full_name or message)
    users = list(result.scalars().all())
    demoish = [
        u
        for u in users
        if _account_status(u) == AccountStatus.PENDING.value
        or u.full_name
        or u.company
        or u.message
        or u.demo_project_id
    ]
    demoish.sort(
        key=lambda u: (
            0 if _account_status(u) == AccountStatus.PENDING.value else 1,
            -(u.id or 0),
        )
    )
    return [_demo_out(u) for u in demoish]


@router.post("/auth/demo-requests/{user_id}/approve", response_model=DemoRequestActionOut)
async def approve_demo_request(
    user_id: int,
    _: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DemoRequestActionOut:
    user = await db.get(AppUser, user_id)
    if user is None or user.role != UserRole.USER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo request not found")

    user.status = AccountStatus.APPROVED.value
    set_demo_window(user)

    if not user.demo_project_id:
        label = user.full_name or user.company or user.username
        profile = get_country_profile(CountryCode.IR)
        project = Project(
            name=f"دمو — {label}",
            country=CountryCode.IR,
            project_type=ProjectType.OFFICE.value,
            country_profile_code=profile.code,
            ui_language=LanguageCode.FA,
            report_language=LanguageCode.FA,
            description=(
                f"پروژه دموی محدود — اعتبار {settings.demo_days_valid} روز، "
                f"حداکثر {settings.demo_max_documents} سند و {settings.demo_max_analyses} تحلیل."
            ),
            owner_user_id=user.id,
            is_demo=True,
        )
        db.add(project)
        await db.flush()
        user.demo_project_id = project.id
        await db.commit()
        await ensure_project_standards(db, project, lang=LanguageCode.FA.value)
    else:
        await db.commit()

    await db.refresh(user)
    return DemoRequestActionOut(
        id=user.id,
        status="approved",
        demo_project_id=user.demo_project_id,
        detail="Demo approved and workspace created",
    )


@router.post("/auth/demo-requests/{user_id}/reject", response_model=DemoRequestActionOut)
async def reject_demo_request(
    user_id: int,
    _: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DemoRequestActionOut:
    user = await db.get(AppUser, user_id)
    if user is None or user.role != UserRole.USER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo request not found")
    user.status = AccountStatus.REJECTED.value
    await db.commit()
    return DemoRequestActionOut(
        id=user.id,
        status="rejected",
        demo_project_id=user.demo_project_id,
        detail="Demo request rejected",
    )


def _is_demo_request_user(user: AppUser) -> bool:
    if user.role != UserRole.USER:
        return False
    if getattr(user, "is_demo_user", False):
        return True
    return bool(
        _account_status(user) == AccountStatus.PENDING.value
        or user.full_name
        or user.company
        or user.message
        or user.demo_project_id
    )


@router.post("/auth/demo-requests/delete", response_model=DemoRequestDeleteOut)
async def delete_demo_requests(
    body: DemoRequestDeleteIn,
    _: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DemoRequestDeleteOut:
    """Admin: delete demo-request users; keep their projects under the admin account."""
    deleted_ids: list[int] = []
    admin = (
        await db.execute(select(AppUser).where(AppUser.username == "admin").limit(1))
    ).scalar_one_or_none()
    admin_id = admin.id if admin is not None else None
    for user_id in dict.fromkeys(body.user_ids):
        user = await db.get(AppUser, user_id)
        if user is None or not _is_demo_request_user(user):
            continue
        # Never remove bootstrap seed accounts by username.
        if user.username in {"admin", "user"} and not getattr(user, "is_demo_user", False):
            continue
        # Keep workspace data: reassign demo/owned projects to admin instead of deleting.
        owned = await db.execute(select(Project).where(Project.owner_user_id == user.id))
        for proj in owned.scalars().all():
            if admin_id is not None:
                proj.owner_user_id = admin_id
            else:
                proj.owner_user_id = None
            proj.is_demo = False
        user.demo_project_id = None
        await db.delete(user)
        deleted_ids.append(user_id)

    if not deleted_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching demo requests to delete")

    await db.commit()
    return DemoRequestDeleteOut(
        deleted_count=len(deleted_ids),
        deleted_ids=deleted_ids,
        detail=f"Deleted {len(deleted_ids)} demo request(s)",
    )
