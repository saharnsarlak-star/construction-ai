"""Project registry: seed categories + items, grouped fetch."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.project_registry_seed import DEFAULT_IMPLEMENTATION_STEPS, REGISTRY_CATEGORIES
from app.models import ImplementationStep, RegistryCategory


async def seed_registry_categories(session: AsyncSession) -> dict[str, int]:
    inserted = 0
    updated = 0
    existing = {
        row.code: row
        for row in (await session.execute(select(RegistryCategory))).scalars().all()
    }

    for row in REGISTRY_CATEGORIES:
        code = str(row["code"]).strip()
        if code in existing:
            cat = existing[code]
            cat.title_fa = str(row["title_fa"])
            cat.title_en = row.get("title_en")
            cat.description_fa = row.get("description_fa")
            cat.sort_order = int(row["sort_order"])
            cat.color_index = int(row.get("color_index") or 0)
            updated += 1
        else:
            session.add(
                RegistryCategory(
                    code=code,
                    title_fa=str(row["title_fa"]),
                    title_en=row.get("title_en"),
                    description_fa=row.get("description_fa"),
                    sort_order=int(row["sort_order"]),
                    color_index=int(row.get("color_index") or 0),
                )
            )
            inserted += 1

    if inserted or updated:
        await session.commit()

    total = int((await session.execute(select(func.count(RegistryCategory.id)))).scalar_one() or 0)
    return {"inserted": inserted, "updated": updated, "table_count": total}


async def seed_implementation_steps(session: AsyncSession) -> dict[str, int]:
    """Insert missing items; backfill empty deliverables/paths on existing rows."""
    count = int((await session.execute(select(func.count(ImplementationStep.id)))).scalar_one() or 0)
    inserted = 0
    backfilled = 0

    by_code = {
        row.step_code: row
        for row in (await session.execute(select(ImplementationStep))).scalars().all()
    }

    for row in DEFAULT_IMPLEMENTATION_STEPS:
        code = str(row["step_code"]).strip().upper()
        if code in by_code:
            existing = by_code[code]
            if not existing.deliverables_fa and row.get("deliverables_fa"):
                existing.deliverables_fa = str(row["deliverables_fa"])
                backfilled += 1
            if not existing.related_paths and row.get("related_paths"):
                existing.related_paths = str(row["related_paths"])
                backfilled += 1
            if existing.is_verified is False and row.get("is_verified"):
                existing.is_verified = bool(row["is_verified"])
                backfilled += 1
            continue

        session.add(
            ImplementationStep(
                step_code=code,
                phase=str(row["phase"]),
                sort_order=int(row["sort_order"]),
                title_fa=str(row["title_fa"]),
                title_en=row.get("title_en"),
                description_fa=row.get("description_fa"),
                description_en=row.get("description_en"),
                status=str(row.get("status") or "pending"),
                category=str(row.get("category") or "general"),
                notes=row.get("notes"),
                deliverables_fa=row.get("deliverables_fa"),
                related_paths=row.get("related_paths"),
                is_verified=bool(row.get("is_verified") or False),
            )
        )
        inserted += 1

    if inserted or backfilled:
        await session.commit()

    total = int((await session.execute(select(func.count(ImplementationStep.id)))).scalar_one() or 0)
    return {
        "inserted": inserted,
        "backfilled": backfilled,
        "table_count": total,
        "was_empty": count == 0,
    }


async def seed_project_registry(session: AsyncSession) -> dict[str, dict[str, int]]:
    cats = await seed_registry_categories(session)
    items = await seed_implementation_steps(session)
    return {"categories": cats, "items": items}


async def load_registry_grouped(session: AsyncSession) -> list[dict]:
    categories = (
        await session.execute(select(RegistryCategory).order_by(RegistryCategory.sort_order, RegistryCategory.id))
    ).scalars().all()
    steps = (
        await session.execute(
            select(ImplementationStep).order_by(ImplementationStep.sort_order, ImplementationStep.id)
        )
    ).scalars().all()

    by_cat: dict[str, list[ImplementationStep]] = defaultdict(list)
    for step in steps:
        by_cat[step.category].append(step)

    groups: list[dict] = []
    seen_cats: set[str] = set()
    for cat in categories:
        seen_cats.add(cat.code)
        groups.append({"category": cat, "items": by_cat.get(cat.code, [])})

    orphan_codes = sorted(set(by_cat.keys()) - seen_cats)
    for code in orphan_codes:
        groups.append({"category": None, "category_code": code, "items": by_cat[code]})

    return groups
