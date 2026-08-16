"""Catalog standard PDF upload (admin) and project-scoped download (user)."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, get_principal, require_admin
from app.database import get_db
from app.models import CatalogStandardAsset, Project, ProjectStandard
from app.schemas import CatalogStandardOut, StandardSectionsOut
from app.services.catalog_standard_text import (
    catalog_asset_is_downloadable,
    extract_catalog_standard_text_background,
)
from app.services.project_standards import ensure_project_standards
from app.services.standard_sections import (
    assert_project_standard_access,
    get_standard_sections,
    persist_taxonomy_mapped_clauses,
)
from app.services.storage import StorageError, open_for_read, save_catalog_standard
from app.tender_taxonomy.standard_codes import resolve_family_code

router = APIRouter(tags=["standards"])


def _normalize_code(raw: str) -> str:
    code = re.sub(r"[^A-Za-z0-9._-]+", "_", (raw or "").strip()).strip("._-")
    if not code:
        raise HTTPException(status_code=400, detail="standard_code is required")
    return code.upper()[:64]


@router.post("/standards/catalog", response_model=CatalogStandardOut)
async def upload_catalog_standard(
    background_tasks: BackgroundTasks,
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
    asset.family_code = resolve_family_code(
        standard_code=code,
        title=title_fa or title,
        original_name=name,
        explicit=asset.family_code,
    )

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
    # Text extraction can take minutes on large Word/PDF files — do not block upload response.
    background_tasks.add_task(extract_catalog_standard_text_background, asset.id)
    return CatalogStandardOut(
        standard_code=asset.standard_code,
        title=asset.title,
        standard_class=asset.standard_class,
        publisher=asset.publisher,
        original_name=asset.original_name,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        has_pdf=catalog_asset_is_downloadable(asset),
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
    if asset is None or not catalog_asset_is_downloadable(asset):
        raise HTTPException(
            status_code=404,
            detail="No original file retained for this standard",
        )

    try:
        path = await open_for_read(asset.stored_path)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not path.exists() or path.stat().st_size < 64:
        raise HTTPException(status_code=404, detail="Standard file is missing or empty on storage")

    media = asset.content_type or "application/octet-stream"
    filename = asset.original_name or f"{code}.pdf"
    return FileResponse(
        path=path,
        media_type=media,
        filename=filename,
    )


@router.get("/standards/{standard_code}/sections", response_model=StandardSectionsOut)
async def list_standard_sections(
    standard_code: str,
    section: str | None = None,
    refresh: bool = False,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> StandardSectionsOut:
    """Taxonomy-grouped sections with stable slot codes (admin / direct catalog access)."""
    _ = principal
    code = _normalize_code(standard_code)
    payload = await get_standard_sections(
        db,
        standard_code=code,
        section_prefix=section,
        refresh=refresh,
    )
    if payload.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Standard not found")
    if payload.get("error") == "no_text":
        raise HTTPException(
            status_code=404,
            detail="Standard text not extracted yet — upload PDF/DOCX or wait for extraction",
        )
    if refresh and principal.is_admin:
        asset = (
            await db.execute(
                select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == code)
            )
        ).scalar_one_or_none()
        if asset is not None:
            await persist_taxonomy_mapped_clauses(
                db,
                asset=asset,
                section_prefix=section,
                force_replace=True,
            )
            payload = await get_standard_sections(
                db,
                standard_code=code,
                section_prefix=section,
                refresh=False,
            )
    return StandardSectionsOut(**payload)


@router.get(
    "/projects/{project_id}/standards/{standard_code}/sections",
    response_model=StandardSectionsOut,
)
async def list_project_standard_sections(
    project_id: int,
    standard_code: str,
    section: str | None = None,
    refresh: bool = False,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> StandardSectionsOut:
    """Project-scoped taxonomy section tree for a selected catalog standard."""
    _ = principal
    code = _normalize_code(standard_code)
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await assert_project_standard_access(db, project_id=project_id, standard_code=code)
    lang = (
        project.ui_language.value
        if hasattr(project.ui_language, "value")
        else str(project.ui_language or "fa")
    )
    payload = await get_standard_sections(
        db,
        standard_code=code,
        lang=lang,
        section_prefix=section,
        refresh=refresh,
    )
    if payload.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Standard not found")
    if payload.get("error") == "no_text":
        raise HTTPException(
            status_code=404,
            detail="Standard text not extracted yet — upload PDF/DOCX or wait for extraction",
        )
    return StandardSectionsOut(**payload)
