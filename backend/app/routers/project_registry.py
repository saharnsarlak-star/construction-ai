"""Grouped project registry API (categories + implementation steps)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_admin
from app.database import get_db
from app.models import ImplementationStep, RegistryCategory
from app.schemas import (
    ImplementationStepOut,
    ProjectRegistryGroupOut,
    ProjectRegistryOut,
    RegistryCategoriesReorder,
    RegistryCategoryOut,
    RegistryCategoryPatch,
    RegistryItemsReorder,
)
from app.services.project_registry import load_registry_grouped

router = APIRouter(tags=["project-registry"])


def _cat_out(row: RegistryCategory) -> RegistryCategoryOut:
    return RegistryCategoryOut.model_validate(row, from_attributes=True)


def _step_out(row: ImplementationStep) -> ImplementationStepOut:
    return ImplementationStepOut.model_validate(row, from_attributes=True)


def _group_out(group: dict) -> ProjectRegistryGroupOut:
    cat = group.get("category")
    if cat is not None:
        return ProjectRegistryGroupOut(
            category=_cat_out(cat),
            category_code=cat.code,
            items=[_step_out(s) for s in group["items"]],
        )
    return ProjectRegistryGroupOut(
        category=None,
        category_code=str(group.get("category_code") or "general"),
        items=[_step_out(s) for s in group["items"]],
    )


@router.get("/project-registry", response_model=ProjectRegistryOut)
async def get_project_registry(
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProjectRegistryOut:
    _ = principal
    groups = await load_registry_grouped(db)
    total_items = sum(len(g["items"]) for g in groups)
    return ProjectRegistryOut(groups=[_group_out(g) for g in groups], total_items=total_items)


@router.patch("/project-registry/categories/{category_id}", response_model=RegistryCategoryOut)
async def patch_registry_category(
    category_id: int,
    body: RegistryCategoryPatch,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RegistryCategoryOut:
    _ = principal
    row = await db.get(RegistryCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")

    for key, value in body.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value.strip()
        setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(row)
    return _cat_out(row)


@router.put("/project-registry/categories/reorder", response_model=list[RegistryCategoryOut])
async def reorder_registry_categories(
    body: RegistryCategoriesReorder,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[RegistryCategoryOut]:
    _ = principal
    if not body.items:
        raise HTTPException(status_code=400, detail="items required")

    ids = [item.id for item in body.items]
    rows = (await db.execute(select(RegistryCategory).where(RegistryCategory.id.in_(ids)))).scalars().all()
    by_id = {r.id: r for r in rows}
    if len(by_id) != len(set(ids)):
        raise HTTPException(status_code=404, detail="One or more categories not found")

    now = datetime.now(timezone.utc)
    for item in body.items:
        cat = by_id[item.id]
        cat.sort_order = item.sort_order
        cat.updated_at = now

    await db.commit()
    all_rows = (
        await db.execute(select(RegistryCategory).order_by(RegistryCategory.sort_order, RegistryCategory.id))
    ).scalars().all()
    return [_cat_out(r) for r in all_rows]


@router.put("/project-registry/items/reorder", response_model=list[ImplementationStepOut])
async def reorder_registry_items(
    body: RegistryItemsReorder,
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
        raise HTTPException(status_code=404, detail="One or more items not found")

    now = datetime.now(timezone.utc)
    for item in body.items:
        step = by_id[item.id]
        step.sort_order = item.sort_order
        step.updated_at = now

    await db.commit()
    reordered = [by_id[i.id] for i in body.items]
    return [_step_out(r) for r in reordered]
