"""Ensure / update ProjectStandard rows from catalog defaults."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.standards_catalog import default_selection_plan, get_standard
from app.models import CountryCode, Project, ProjectStandard


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
            continue
        # Refresh metadata always
        row.applicability_level = level
        row.standard_class = standard.standard_class
        row.title = title
        if row.selected_by == "system_default":
            row.is_selected = auto

    # Remove obsolete system_default rows no longer in country catalog (keep overrides)
    for code, row in list(existing.items()):
        if code not in plan_codes and row.selected_by == "system_default":
            await db.delete(row)
            existing.pop(code, None)

    await db.commit()
    result = await db.execute(
        select(ProjectStandard)
        .where(ProjectStandard.project_id == project.id)
        .order_by(ProjectStandard.standard_code)
    )
    return list(result.scalars().all())


async def apply_user_standard_selection(
    db: AsyncSession,
    project: Project,
    updates: list[tuple[str, bool]],
) -> list[ProjectStandard]:
    await ensure_project_standards(db, project)
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
                title=std.title_en,
            )
            db.add(row)
            by_code[code] = row
        else:
            row.is_selected = is_selected
            row.selected_by = "user_override"
    await db.commit()
    return await ensure_project_standards(db, project)
