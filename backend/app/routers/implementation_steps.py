"""Admin CRUD + reorder for implementation roadmap steps."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_admin
from app.database import get_db
from app.models import ImplementationStep
from app.schemas import (
    ImplementationStepCreate,
    ImplementationStepOut,
    ImplementationStepPatch,
    ImplementationStepsReorder,
)

router = APIRouter(tags=["implementation-steps"])

_VALID_STATUS = frozenset({"pending", "in_progress", "completed", "verified", "blocked"})


def _out(row: ImplementationStep) -> ImplementationStepOut:
    return ImplementationStepOut.model_validate(row, from_attributes=True)


@router.get("/implementation-steps", response_model=list[ImplementationStepOut])
async def list_implementation_steps(
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ImplementationStepOut]:
    _ = principal
    rows = (
        await db.execute(select(ImplementationStep).order_by(ImplementationStep.sort_order, ImplementationStep.id))
    ).scalars().all()
    return [_out(r) for r in rows]


@router.post("/implementation-steps", response_model=ImplementationStepOut, status_code=status.HTTP_201_CREATED)
async def create_implementation_step(
    body: ImplementationStepCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ImplementationStepOut:
    _ = principal
    code = body.step_code.strip().upper()
    exists = (
        await db.execute(select(ImplementationStep.id).where(ImplementationStep.step_code == code))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="step_code already exists")

    if body.status not in _VALID_STATUS:
        raise HTTPException(status_code=400, detail="invalid status")

    max_order = (
        await db.execute(select(func.max(ImplementationStep.sort_order)))
    ).scalar_one_or_none()
    sort_order = body.sort_order if body.sort_order is not None else int(max_order or 0) + 10

    row = ImplementationStep(
        step_code=code,
        phase=body.phase.strip(),
        sort_order=sort_order,
        title_fa=body.title_fa.strip(),
        title_en=(body.title_en or "").strip() or None,
        description_fa=(body.description_fa or "").strip() or None,
        description_en=(body.description_en or "").strip() or None,
        status=body.status,
        category=(body.category or "general").strip(),
        notes=(body.notes or "").strip() or None,
        deliverables_fa=(body.deliverables_fa or "").strip() or None,
        related_paths=(body.related_paths or "").strip() or None,
        is_verified=bool(body.is_verified),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.patch("/implementation-steps/{step_id}", response_model=ImplementationStepOut)
async def patch_implementation_step(
    step_id: int,
    body: ImplementationStepPatch,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ImplementationStepOut:
    _ = principal
    row = await db.get(ImplementationStep, step_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Step not found")

    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in _VALID_STATUS:
        raise HTTPException(status_code=400, detail="invalid status")
    if "step_code" in data:
        data["step_code"] = data["step_code"].strip().upper()

    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.put("/implementation-steps/reorder", response_model=list[ImplementationStepOut])
async def reorder_implementation_steps(
    body: ImplementationStepsReorder,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ImplementationStepOut]:
    _ = principal
    if not body.items:
        raise HTTPException(status_code=400, detail="items required")

    ids = [item.id for item in body.items]
    rows = (await db.execute(select(ImplementationStep).where(ImplementationStep.id.in_(ids)))).scalars().all()
    by_id = {r.id: r for r in rows}
    if len(by_id) != len(set(ids)):
        raise HTTPException(status_code=404, detail="One or more steps not found")

    now = datetime.now(timezone.utc)
    for item in body.items:
        row = by_id[item.id]
        row.sort_order = item.sort_order
        row.updated_at = now

    await db.commit()
    all_rows = (
        await db.execute(select(ImplementationStep).order_by(ImplementationStep.sort_order, ImplementationStep.id))
    ).scalars().all()
    return [_out(r) for r in all_rows]


@router.delete("/implementation-steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_implementation_step(
    step_id: int,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _ = principal
    row = await db.get(ImplementationStep, step_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Step not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
