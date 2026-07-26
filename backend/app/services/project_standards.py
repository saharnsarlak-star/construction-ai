"""Ensure / update ProjectStandard rows from catalog defaults."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.standards_catalog import default_selection_plan, get_standard
from app.models import CountryCode, Project, ProjectStandard


async def _fetch_rows(db: AsyncSession, project_id: int) -> list[ProjectStandard]:
    result = await db.execute(
        select(ProjectStandard)
        .where(ProjectStandard.project_id == project_id)
        .order_by(ProjectStandard.standard_code)
    )
    return list(result.scalars().all())


async def ensure_project_standards(db: AsyncSession, project: Project, *, lang: str = "fa") -> list[ProjectStandard]:
    """
    Sync catalog visibility for this project's country/type.
    - Insert missing catalog rows with system defaults.
    - Refresh system_default rows when country/type changed.
    - Never overwrite user_override selections.
    """
    country = project.country if isinstance(project.country, CountryCode) else CountryCode(str(project.country))
    ptype = project.project_type or "infrastructure"
    plan = default_selection_plan(country, ptype)

    result = await db.execute(select(ProjectStandard).where(ProjectStandard.project_id == project.id))
    existing = {row.standard_code: row for row in result.scalars().all()}
    plan_codes = {s.code for s, _, _ in plan}
    dirty = False

    for standard, level, auto in plan:
        title = standard.title_for(lang)
        row = existing.get(standard.code)
        if row is None:
            row = ProjectStandard(
                project_id=project.id,
                standard_code=standard.code,
                is_selected=auto,
                selected_by="system_default",
                applicability_level=level,
                standard_class=standard.standard_class,
                title=title,
            )
            db.add(row)
            existing[standard.code] = row
            dirty = True
            continue
        if (
            row.applicability_level != level
            or row.standard_class != standard.standard_class
            or row.title != title
        ):
            row.applicability_level = level
            row.standard_class = standard.standard_class
            row.title = title
            dirty = True
        if row.selected_by == "system_default" and row.is_selected != auto:
            row.is_selected = auto
            dirty = True

    for code, row in list(existing.items()):
        if code not in plan_codes and row.selected_by == "system_default":
            await db.delete(row)
            existing.pop(code, None)
            dirty = True

    if dirty:
        await db.commit()
    return await _fetch_rows(db, project.id)


async def list_or_seed_project_standards(
    db: AsyncSession, project: Project, *, lang: str = "fa"
) -> list[ProjectStandard]:
    """Return rows; seed missing catalog codes without forcing a full wipe."""
    rows = await _fetch_rows(db, project.id)
    country = project.country if isinstance(project.country, CountryCode) else CountryCode(str(project.country))
    plan = default_selection_plan(country, project.project_type or "infrastructure")
    existing = {r.standard_code for r in rows}
    if not rows or any(s.code not in existing for s, _, _ in plan):
        return await ensure_project_standards(db, project, lang=lang)
    return rows


async def apply_user_standard_selection(
    db: AsyncSession,
    project: Project,
    updates: list[tuple[str, bool]],
    *,
    lang: str = "fa",
) -> list[ProjectStandard]:
    """Lightweight toggle — update only requested rows, one commit."""
    result = await db.execute(select(ProjectStandard).where(ProjectStandard.project_id == project.id))
    by_code = {row.standard_code: row for row in result.scalars().all()}
    if not by_code:
        await ensure_project_standards(db, project, lang=lang)
        result = await db.execute(select(ProjectStandard).where(ProjectStandard.project_id == project.id))
        by_code = {row.standard_code: row for row in result.scalars().all()}

    for code, is_selected in updates:
        row = by_code.get(code)
        if row is None:
            std = get_standard(code)
            if not std:
                continue
            row = ProjectStandard(
                project_id=project.id,
                standard_code=code,
                is_selected=is_selected,
                selected_by="user_override",
                applicability_level="optional",
                standard_class=std.standard_class,
                title=std.title_for(lang),
            )
            db.add(row)
            by_code[code] = row
        else:
            row.is_selected = is_selected
            row.selected_by = "user_override"

    await db.commit()
    # Return only touched codes' current state is enough for API; keep full list for compatibility
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
