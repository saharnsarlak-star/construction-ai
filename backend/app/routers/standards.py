"""Catalog standard PDF upload (admin) and project-scoped download (user)."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, get_principal, require_admin
from app.database import get_db
from app.models import CatalogStandardAsset, Project, ProjectStandard
from app.schemas import CatalogStandardOut
from app.services.project_standards import ensure_project_standards
from app.services.storage import StorageError, open_for_read, save_catalog_standard

router = APIRouter(tags=["standards"])


def _normalize_code(raw: str) -> str:
    code = re.sub(r"[^A-Za-z0-9._-]+", "_", (raw or "").strip()).strip("._-")
    if not code:
        raise HTTPException(status_code=400, detail="standard_code is required")
    return code.upper()[:64]


@router.post("/standards/catalog", response_model=CatalogStandardOut)
async def upload_catalog_standard(
    file: Annotated[UploadFile, File()],
    standard_code: Annotated[str, Form()],
    title: Annotated[str, Form()],
    standard_class: Annotated[str, Form()] = "technical",
    publisher: Annotated[str | None, Form()] = None,
    title_fa: Annotated[str | None, Form()] = None,
    title_en: Annotated[str | None, Form()] = None,
    title_de: Annotated[str | None, Form()] = None,
    project_id: Annotated[int | None, Form()] = None,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CatalogStandardOut:
    """Admin-only: add/replace original PDF for a catalog standard code."""
    code = _normalize_code(standard_code)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    name = file.filename or f"{code}.pdf"
    content_type = file.content_type or "application/pdf"

    try:
        stored_path, _local = await save_catalog_standard(
            standard_code=code,
            filename=name,
            data=data,
            content_type=content_type,
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = await db.execute(
        select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == code)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        asset = CatalogStandardAsset(standard_code=code)
        db.add(asset)

    asset.title = title.strip() or code
    asset.title_fa = title_fa
    asset.title_en = title_en or title
    asset.title_de = title_de
    asset.publisher = publisher or "custom"
    asset.standard_class = (standard_class or "technical").strip() or "technical"
    asset.original_name = name
    asset.stored_path = stored_path
    asset.content_type = content_type
    asset.size_bytes = len(data)
    asset.uploaded_by = principal.username
    asset.extracted_text = None
    asset.extraction_status = "pending"

    # Optionally surface on a project checklist immediately
    if project_id is not None:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        lang = (
            project.report_language.value
            if hasattr(project.report_language, "value")
            else str(project.report_language or "en")
        )
        await db.flush()
        await ensure_project_standards(db, project, lang=lang)
        existing = (
            await db.execute(
                select(ProjectStandard).where(
                    ProjectStandard.project_id == project_id,
                    ProjectStandard.standard_code == code,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                ProjectStandard(
                    project_id=project_id,
                    standard_code=code,
                    is_selected=True,
                    selected_by="user_override",
                    applicability_level="optional",
                    standard_class=asset.standard_class,
                    title=asset.title,
                )
            )
        else:
            existing.is_selected = True
            existing.selected_by = "user_override"
            existing.title = asset.title
            existing.standard_class = asset.standard_class

    await db.commit()
    await db.refresh(asset)
    # Best-effort: extract catalog PDF text so the next analysis can use it immediately.
    try:
        from app.services.catalog_standard_text import ensure_catalog_standard_text

        await ensure_catalog_standard_text(db, asset)
        await db.refresh(asset)
    except Exception:  # noqa: BLE001
        pass
    return CatalogStandardOut(
        standard_code=asset.standard_code,
        title=asset.title,
        standard_class=asset.standard_class,
        publisher=asset.publisher,
        original_name=asset.original_name,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        has_pdf=True,
        created_at=asset.created_at,
    )


@router.get("/projects/{project_id}/standards/{standard_code}/download")
async def download_project_standard_pdf(
    project_id: int,
    standard_code: str,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    """
    User (or admin) may download the original PDF of a standard that appears
    on the project checklist (selected or listed as applicable).
    """
    _ = principal  # anonymous USER allowed for MVP project access
    code = _normalize_code(standard_code)
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = (
        await db.execute(
            select(ProjectStandard).where(
                ProjectStandard.project_id == project_id,
                ProjectStandard.standard_code == code,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=403,
            detail="Standard is not on this project's applicable/selected list",
        )

    asset = (
        await db.execute(
            select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == code)
        )
    ).scalar_one_or_none()
    if asset is None or not asset.stored_path:
        raise HTTPException(
            status_code=404,
            detail="No original PDF retained for this standard",
        )

    try:
        path = await open_for_read(asset.stored_path)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media = asset.content_type or "application/pdf"
    return FileResponse(
        path=path,
        media_type=media,
        filename=asset.original_name or f"{code}.pdf",
    )
