"""Phase 6 — Risk Knowledge Base internal API (GET list/detail, Admin PATCH)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, get_principal, require_admin
from app.config import settings
from app.database import get_db
from app.knowledge.rkb import (
    list_risks_from_db,
    list_risks_from_python,
    risk_to_dict,
    seed_risks_table,
)
from app.models import Risk
from app.schemas import RiskOut, RiskPatch, RiskSeedOut

router = APIRouter(tags=["risks"])


def _as_risk_out(row: dict) -> RiskOut:
    return RiskOut.model_validate(row)


@router.get("/risks", response_model=list[RiskOut])
async def list_risks(
    active_only: bool = Query(True),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> list[RiskOut]:
    """List RKB entries. Uses DB when RKB_DB_ENABLED, else Python seed dicts."""
    _ = principal
    if settings.rkb_db_enabled:
        rows = await list_risks_from_db(db, active_only=active_only)
        if not rows:
            # Ensure seed landed even if init_db was skipped
            await seed_risks_table(db)
            rows = await list_risks_from_db(db, active_only=active_only)
    else:
        rows = list_risks_from_python()
        if active_only:
            rows = [r for r in rows if r.get("is_active", True)]
    return [_as_risk_out(r) for r in rows]


@router.get("/risks/{risk_id}", response_model=RiskOut)
async def get_risk(
    risk_id: str,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> RiskOut:
    _ = principal
    rid = risk_id.strip()
    if settings.rkb_db_enabled:
        row = (
            await db.execute(select(Risk).where(Risk.risk_id == rid))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Risk {rid} not found")
        return _as_risk_out(risk_to_dict(row))
    catalog = {r["risk_id"]: r for r in list_risks_from_python()}
    if rid not in catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Risk {rid} not found")
    return _as_risk_out(catalog[rid])


@router.patch("/risks/{risk_id}", response_model=RiskOut)
async def patch_risk(
    risk_id: str,
    body: RiskPatch,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RiskOut:
    """Admin-only update. Requires RKB_DB_ENABLED so edits persist in the database."""
    _ = principal
    if not settings.rkb_db_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Set RKB_DB_ENABLED=true to persist Risk Knowledge Base edits",
        )
    rid = risk_id.strip()
    row = (await db.execute(select(Risk).where(Risk.risk_id == rid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Risk {rid} not found")

    data = body.model_dump(exclude_unset=True)
    if "related_standards" in data:
        row.related_standards_json = json.dumps(data.pop("related_standards") or [], ensure_ascii=False)
    if "related_documents" in data:
        row.related_documents_json = json.dumps(data.pop("related_documents") or [], ensure_ascii=False)
    for key, value in data.items():
        setattr(row, key, value)
    row.version = int(row.version or 1) + 1
    await db.commit()
    await db.refresh(row)
    return _as_risk_out(risk_to_dict(row))


@router.post("/risks/seed", response_model=RiskSeedOut)
async def seed_risks(
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RiskSeedOut:
    """Admin: upsert the 46 seed Risk IDs into the risks table (additive)."""
    _ = principal
    stats = await seed_risks_table(db)
    return RiskSeedOut(**stats)
