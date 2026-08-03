"""Phase 7 — Experience Knowledge admin API (CRUD + bulk + categorize)."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, get_principal, require_admin
from app.database import get_db
from app.models import ExperienceKnowledgeItem
from app.schemas import (
    ExperienceBulkCreate,
    ExperienceBulkOut,
    ExperienceCreate,
    ExperienceOut,
    ExperiencePatch,
    ExperienceSuggestOut,
)
from app.services.experience_layer import (
    EXPERIENCE_CATEGORIES,
    item_to_dict,
    normalize_origin_kind,
    parse_bulk_experience_text,
    suggest_category,
    suggest_experience_id,
    suggest_match_keywords,
    suggest_title_from_text,
)

router = APIRouter(tags=["experience"])


def _out(item: ExperienceKnowledgeItem) -> ExperienceOut:
    return ExperienceOut.model_validate(item_to_dict(item))


def _types_from_body(body: ExperienceCreate) -> list[str]:
    types = list(body.related_project_types or [])
    if body.related_project_type and body.related_project_type not in types:
        types.append(body.related_project_type)
    return types


async def _unique_experience_id(db: AsyncSession, preferred: str) -> str:
    eid = preferred.strip() or f"EXP-{uuid.uuid4().hex[:10].upper()}"
    existing = (
        await db.execute(
            select(ExperienceKnowledgeItem).where(ExperienceKnowledgeItem.experience_id == eid)
        )
    ).scalar_one_or_none()
    if existing is None:
        return eid
    return f"{eid}-{uuid.uuid4().hex[:6].upper()}"[:120]


async def _create_one(
    db: AsyncSession,
    *,
    body: ExperienceCreate,
    principal: Principal,
    auto_categorize: bool = False,
) -> ExperienceKnowledgeItem:
    title = body.title.strip()
    description = (body.description or "").strip()
    blob = f"{title}\n{description}"
    category = (body.category or "").strip()
    if not category or category == "lesson":
        if auto_categorize:
            category = suggest_category(blob)
    if not category:
        category = "lesson"

    keywords = list(body.match_keywords or [])
    if not keywords:
        keywords = suggest_match_keywords(blob)

    eid = await _unique_experience_id(
        db,
        (body.experience_id or "").strip() or suggest_experience_id(title, category),
    )
    types = _types_from_body(body)
    item = ExperienceKnowledgeItem(
        experience_id=eid,
        title=title,
        description=description,
        category=category,
        origin_kind=normalize_origin_kind(body.origin_kind),
        source=body.source or f"admin:{principal.username}",
        author=body.author or principal.username,
        validation_status=(body.validation_status or "validated").strip().lower(),
        confidence_level=(body.confidence_level or "medium").strip().lower(),
        related_risk_id=(body.related_risk_id or body.related_risk or None),
        related_risk_category=body.related_risk_category or category,
        related_project_types_json=json.dumps(types, ensure_ascii=False) if types else None,
        recommended_prevention=body.recommended_prevention or body.prevention,
        match_keywords_json=json.dumps(keywords, ensure_ascii=False) if keywords else None,
        is_active=True,
        version=1,
    )
    db.add(item)
    return item


@router.get("/experience/categories")
async def list_experience_categories(
    principal: Principal = Depends(get_principal),
) -> dict:
    _ = principal
    return {
        "categories": [
            {"code": code, "keywords_sample": kws[:6]}
            for code, kws in EXPERIENCE_CATEGORIES.items()
        ]
        + [{"code": "lesson", "keywords_sample": []}]
    }


class _SuggestIn(BaseModel):
    text: str = Field(min_length=1)


@router.post("/experience/suggest", response_model=ExperienceSuggestOut)
async def suggest_experience_fields(
    body: _SuggestIn,
    principal: Principal = Depends(require_admin),
) -> ExperienceSuggestOut:
    _ = principal
    text = body.text.strip()
    return ExperienceSuggestOut(
        category=suggest_category(text),
        match_keywords=suggest_match_keywords(text),
        title_suggestion=suggest_title_from_text(text),
    )


@router.get("/experience", response_model=list[ExperienceOut])
async def list_experience(
    active_only: bool = Query(False),
    category: str | None = Query(None),
    q: str | None = Query(None),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ExperienceOut]:
    _ = principal
    stmt = select(ExperienceKnowledgeItem).order_by(ExperienceKnowledgeItem.experience_id)
    if active_only:
        stmt = stmt.where(ExperienceKnowledgeItem.is_active.is_(True))
    if category:
        stmt = stmt.where(ExperienceKnowledgeItem.category == category.strip())
    rows = list((await db.execute(stmt)).scalars().all())
    if q and q.strip():
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if needle in (r.title or "").lower()
            or needle in (r.description or "").lower()
            or needle in (r.experience_id or "").lower()
            or needle in (r.category or "").lower()
        ]
    return [_out(r) for r in rows]


@router.get("/experience/{experience_id}", response_model=ExperienceOut)
async def get_experience(
    experience_id: str,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> ExperienceOut:
    _ = principal
    row = (
        await db.execute(
            select(ExperienceKnowledgeItem).where(
                ExperienceKnowledgeItem.experience_id == experience_id.strip()
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experience item not found")
    return _out(row)


@router.post("/experience", response_model=ExperienceOut, status_code=status.HTTP_201_CREATED)
async def create_experience(
    body: ExperienceCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ExperienceOut:
    """Admin: create a curated ExperienceKnowledgeItem."""
    item = await _create_one(db, body=body, principal=principal, auto_categorize=True)
    await db.commit()
    await db.refresh(item)
    return _out(item)


@router.post("/experience/bulk", response_model=ExperienceBulkOut, status_code=status.HTTP_201_CREATED)
async def create_experience_bulk(
    body: ExperienceBulkCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ExperienceBulkOut:
    """Admin: create many experiences from structured items and/or pasted raw text."""
    payloads: list[ExperienceCreate] = list(body.items or [])
    if body.raw_text and body.raw_text.strip():
        for block in parse_bulk_experience_text(body.raw_text):
            payloads.append(
                ExperienceCreate(
                    title=block["title"],
                    description=block["description"],
                    category=body.default_category or "lesson",
                    related_project_types=list(body.default_project_types or []),
                )
            )

    created: list[ExperienceKnowledgeItem] = []
    skipped = 0
    for payload in payloads:
        title = (payload.title or "").strip()
        if len(title) < 3:
            skipped += 1
            continue
        if body.default_category and (not payload.category or payload.category == "lesson"):
            payload.category = body.default_category
        if body.default_project_types and not payload.related_project_types:
            payload.related_project_types = list(body.default_project_types)
        item = await _create_one(
            db,
            body=payload,
            principal=principal,
            auto_categorize=body.auto_categorize,
        )
        created.append(item)

    await db.commit()
    for item in created:
        await db.refresh(item)
    return ExperienceBulkOut(
        created=[_out(i) for i in created],
        created_count=len(created),
        skipped=skipped,
    )


@router.delete("/experience/{experience_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_experience(
    experience_id: str,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Admin: permanently delete an experience item."""
    _ = principal
    row = (
        await db.execute(
            select(ExperienceKnowledgeItem).where(
                ExperienceKnowledgeItem.experience_id == experience_id.strip()
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experience item not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/experience/{experience_id}", response_model=ExperienceOut)
async def patch_experience(
    experience_id: str,
    body: ExperiencePatch,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ExperienceOut:
    _ = principal
    row = (
        await db.execute(
            select(ExperienceKnowledgeItem).where(
                ExperienceKnowledgeItem.experience_id == experience_id.strip()
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experience item not found")

    data = body.model_dump(exclude_unset=True)
    if "related_project_types" in data:
        types = data.pop("related_project_types") or []
        row.related_project_types_json = json.dumps(types, ensure_ascii=False)
    if "related_project_type" in data:
        single = data.pop("related_project_type")
        if single:
            types = json.loads(row.related_project_types_json or "[]")
            if single not in types:
                types.append(single)
            row.related_project_types_json = json.dumps(types, ensure_ascii=False)
    if "match_keywords" in data:
        kws = data.pop("match_keywords") or []
        row.match_keywords_json = json.dumps(kws, ensure_ascii=False)
    if "origin_kind" in data and data["origin_kind"] is not None:
        data["origin_kind"] = normalize_origin_kind(data["origin_kind"])
    if "related_risk" in data:
        risk = data.pop("related_risk")
        if risk is not None:
            row.related_risk_id = risk
    if "prevention" in data:
        prev = data.pop("prevention")
        if prev is not None:
            row.recommended_prevention = prev
    for key, value in data.items():
        if hasattr(row, key):
            setattr(row, key, value)
    row.version = int(row.version or 1) + 1
    await db.commit()
    await db.refresh(row)
    return _out(row)
