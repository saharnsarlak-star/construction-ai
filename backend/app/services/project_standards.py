"""Project standard checklist driven by admin-uploaded catalog PDFs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.standards_catalog import default_selection_plan, get_standard
from app.models import CatalogStandardAsset, CountryCode, Project, ProjectStandard


async def _fetch_rows(db: AsyncSession, project_id: int) -> list[ProjectStandard]:
    result = await db.execute(
        select(ProjectStandard)
        .where(ProjectStandard.project_id == project_id)
        .order_by(ProjectStandard.standard_code)
    )
    return list(result.scalars().all())


def _title_for_asset(asset: CatalogStandardAsset, lang: str) -> str:
    """Prefer localized catalog asset titles, then code-catalog titles, then asset.title."""
    if lang == "fa" and asset.title_fa:
        return asset.title_fa
    if lang == "de" and asset.title_de:
        return asset.title_de
    if lang == "en" and asset.title_en:
        return asset.title_en
    std = get_standard(asset.standard_code)
    if std:
        return std.title_for(lang)
    return asset.title or asset.standard_code


async def ensure_project_standards(db: AsyncSession, project: Project, *, lang: str = "fa") -> list[ProjectStandard]:
    """
    Sync the project checklist to admin-uploaded catalog PDFs only.

    Product rule:
    - Admin uploads original PDFs into CatalogStandardAsset.
    - Users see that list, select which apply, and download PDFs.
    - The in-code standards_catalog.py is metadata/hints only — it does NOT
      invent checklist rows without a retained PDF.
    """
    country = project.country if isinstance(project.country, CountryCode) else CountryCode(str(project.country))
    ptype = project.project_type or "infrastructure"
    plan = {s.code: (level, auto) for s, level, auto in default_selection_plan(country, ptype)}

    result = await db.execute(select(ProjectStandard).where(ProjectStandard.project_id == project.id))
    existing = {row.standard_code: row for row in result.scalars().all()}

    asset_rows = list(
        (
            await db.execute(select(CatalogStandardAsset).order_by(CatalogStandardAsset.standard_code))
        ).scalars().all()
    )
    asset_codes = {a.standard_code for a in asset_rows}
    dirty = False

    for asset in asset_rows:
        if not asset.stored_path:
            continue
        title = _title_for_asset(asset, lang)
        std = get_standard(asset.standard_code)
        sclass = asset.standard_class or (std.standard_class if std else "technical")
        level, auto = plan.get(asset.standard_code, ("optional", False))
        row = existing.get(asset.standard_code)
        if row is None:
            db.add(
                ProjectStandard(
                    project_id=project.id,
                    standard_code=asset.standard_code,
                    is_selected=bool(auto),
                    selected_by="system_default",
                    applicability_level=level,
                    standard_class=sclass,
                    title=title,
                )
            )
            dirty = True
            continue
        # Refresh display metadata; never overwrite user_override selection.
        if row.title != title or row.standard_class != sclass or row.applicability_level != level:
            row.title = title
            row.standard_class = sclass
            row.applicability_level = level
            dirty = True
        if row.selected_by == "system_default" and row.is_selected != bool(auto):
            row.is_selected = bool(auto)
            dirty = True

    # Drop checklist rows that have no admin PDF (legacy code-catalog seeds).
    for code, row in list(existing.items()):
        if code not in asset_codes:
            await db.delete(row)
            existing.pop(code, None)
            dirty = True

    if dirty:
        await db.commit()
    return await _fetch_rows(db, project.id)


async def list_or_seed_project_standards(
    db: AsyncSession, project: Project, *, lang: str = "fa"
) -> list[ProjectStandard]:
    """Return rows synced to current catalog PDFs."""
    return await ensure_project_standards(db, project, lang=lang)


async def apply_user_standard_selection(
    db: AsyncSession,
    project: Project,
    updates: list[tuple[str, bool]],
    *,
    lang: str = "fa",
) -> list[ProjectStandard]:
    """Toggle selection only for standards that have an admin-uploaded PDF."""
    await ensure_project_standards(db, project, lang=lang)
    result = await db.execute(select(ProjectStandard).where(ProjectStandard.project_id == project.id))
    by_code = {row.standard_code: row for row in result.scalars().all()}

    asset_codes = set(
        (
            await db.execute(select(CatalogStandardAsset.standard_code))
        ).scalars().all()
    )

    for code, is_selected in updates:
        if code not in asset_codes:
            continue
        row = by_code.get(code)
        if row is None:
            continue
        row.is_selected = is_selected
        row.selected_by = "user_override"

    await db.commit()
    return await _fetch_rows(db, project.id)


async def toggle_one_standard(
    db: AsyncSession,
    *,
    project_id: int,
    standard_code: str,
    is_selected: bool,
) -> ProjectStandard | None:
    """Minimal path for a single checkbox — no document loading, no full resync."""
    result = await db.execute(
        select(ProjectStandard).where(
            ProjectStandard.project_id == project_id,
            ProjectStandard.standard_code == standard_code,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.is_selected = is_selected
    row.selected_by = "user_override"
    await db.commit()
    await db.refresh(row)
    return row
