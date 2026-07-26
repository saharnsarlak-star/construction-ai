import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Analysis, Document, DocumentCategory, Finding, Project, ProjectStandard, ProjectType
from app.schemas import (
    AnalysisOut,
    AnalyzeRequest,
    DocumentOut,
    FindingOut,
    ProjectCreate,
    ProjectOut,
    ProjectStandardOut,
    ProjectStandardsUpdate,
    ProjectUpdate,
    UploadBatchOut,
    UploadErrorOut,
)
from app.services.analyzer import analyze_project_documents
from app.services.extractor import SUPPORTED_EXTENSIONS, extract_text_from_file, has_usable_text
from app.services import storage as file_storage
from app.services.project_standards import (
    ensure_project_standards,
    list_or_seed_project_standards,
    toggle_one_standard,
)
from app.knowledge.country_profiles import get_country_profile
from app.knowledge.standards_catalog import get_standard

router = APIRouter(prefix="/projects", tags=["projects"])


def _doc_out(doc: Document) -> DocumentOut:
    text = doc.extracted_text or ""
    return DocumentOut(
        id=doc.id,
        category=doc.category,
        original_name=doc.original_name,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        has_text=has_usable_text(text),
        ocr_applied=text.lstrip().startswith("[OCR_APPLIED]"),
        created_at=doc.created_at,
    )


def _project_out(project: Project) -> ProjectOut:
    raw_type = getattr(project, "project_type", None) or ProjectType.INFRASTRUCTURE.value
    if isinstance(raw_type, ProjectType):
        ptype = raw_type
    else:
        try:
            ptype = ProjectType(str(raw_type))
        except ValueError:
            ptype = ProjectType.INFRASTRUCTURE
    return ProjectOut(
        id=project.id,
        name=project.name,
        country=project.country,
        project_type=ptype,
        country_profile_code=getattr(project, "country_profile_code", None),
        ui_language=project.ui_language,
        report_language=project.report_language,
        description=project.description,
        created_at=project.created_at,
        documents=[_doc_out(d) for d in project.documents],
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectOut]:
    try:
        result = await db.execute(
            select(Project).options(selectinload(Project.documents)).order_by(Project.id.desc())
        )
        return [_project_out(p) for p in result.scalars().all()]
    except Exception as exc:  # noqa: BLE001
        # Surface DB/schema errors to the client so CORS+500 is diagnosable.
        raise HTTPException(status_code=500, detail=f"list_projects failed: {exc}") from exc


@router.post("", response_model=ProjectOut)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    data = payload.model_dump()
    profile = get_country_profile(payload.country)
    data["country_profile_code"] = profile.code
    # DB column is varchar
    if hasattr(data.get("project_type"), "value"):
        data["project_type"] = data["project_type"].value
    project = Project(**data)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    await ensure_project_standards(db, project, lang=payload.ui_language.value)
    # Reload with selectinload so async relationship access is safe.
    project = await _get_project(db, project.id)
    return _project_out(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    project = await _get_project(db, project_id)
    return _project_out(project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    project = await _get_project(db, project_id)
    country_or_type_changed = False
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "project_type" and hasattr(value, "value"):
            value = value.value
        if key in {"country", "project_type"} and value is not None and getattr(project, key, None) != value:
            country_or_type_changed = True
        if key == "country" and value is not None:
            setattr(project, key, value)
            project.country_profile_code = get_country_profile(value).code
            continue
        setattr(project, key, value)
    await db.commit()
    project = await _get_project(db, project_id)
    if country_or_type_changed:
        await ensure_project_standards(db, project, lang=project.ui_language.value)
    return _project_out(project)


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    project = await _get_project(db, project_id)
    await db.delete(project)
    await db.commit()
    return {"ok": True}


def _standard_out(row: ProjectStandard) -> ProjectStandardOut:
    std = get_standard(row.standard_code)
    sclass = row.standard_class or (std.standard_class if std else "technical")
    if sclass == "contractual":
        check_target = "contract"
    elif sclass == "hybrid":
        check_target = "contract+technical"
    else:
        check_target = "drawings+boq+specifications"
    return ProjectStandardOut(
        standard_code=row.standard_code,
        title=row.title or (std.title_en if std else row.standard_code),
        standard_class=sclass,
        publisher=std.publisher if std else "",
        applicability_level=row.applicability_level or "optional",
        is_selected=bool(row.is_selected),
        selected_by=row.selected_by or "system_default",
        check_target=check_target,
    )


@router.get("/{project_id}/standards", response_model=list[ProjectStandardOut])
async def list_project_standards(
    project_id: int, db: AsyncSession = Depends(get_db)
) -> list[ProjectStandardOut]:
    project = await _get_project_meta(db, project_id)
    rows = await list_or_seed_project_standards(db, project, lang=project.ui_language.value)
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            0 if r.is_selected else 1,
            0 if (r.applicability_level or "") == "mandatory_default" else 1,
            r.standard_code,
        ),
    )
    return [_standard_out(r) for r in rows_sorted]


@router.put("/{project_id}/standards", response_model=list[ProjectStandardOut])
async def update_project_standards(
    project_id: int,
    payload: ProjectStandardsUpdate,
    db: AsyncSession = Depends(get_db),
) -> list[ProjectStandardOut]:
    """Fast path: toggle without loading project documents (avoids multi-second hangs)."""
    await _get_project_meta(db, project_id)
    # Prefer single-item toggle path used by the UI
    if len(payload.items) == 1:
        item = payload.items[0]
        row = await toggle_one_standard(
            db,
            project_id=project_id,
            standard_code=item.standard_code,
            is_selected=item.is_selected,
        )
        if row is not None:
            return [_standard_out(row)]
    # Fallback: seed then toggle
    project = await _get_project_meta(db, project_id)
    rows = await list_or_seed_project_standards(db, project, lang=project.ui_language.value)
    by_code = {r.standard_code: r for r in rows}
    for item in payload.items:
        row = by_code.get(item.standard_code)
        if row is None:
            continue
        row.is_selected = item.is_selected
        row.selected_by = "user_override"
    await db.commit()
    # Return only updated rows so the client can merge without reshuffling the whole list
    out = []
    for item in payload.items:
        row = by_code.get(item.standard_code)
        if row is not None:
            await db.refresh(row)
            out.append(_standard_out(row))
    return out


@router.post("/{project_id}/documents", response_model=UploadBatchOut)
async def upload_documents(
    project_id: int,
    category: Annotated[DocumentCategory, Form()],
    files: Annotated[list[UploadFile], File()],
    db: AsyncSession = Depends(get_db),
) -> UploadBatchOut:
    """
    Accept many files in one request. Failures are per-file (partial success).
    Drawing uploads skip OCR so bulk plan packages do not time out.
    """
    project = await _get_project(db, project_id)
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    max_bytes = (
        None if settings.max_upload_mb <= 0 else settings.max_upload_mb * 1024 * 1024
    )
    # Skip OCR for drawings always; also for larger batches so uploads finish.
    allow_ocr = category != DocumentCategory.DRAWING and len(files) <= 2
    saved: list[Document] = []
    errors: list[UploadErrorOut] = []

    for upload in files:
        name = upload.filename or "unnamed"
        suffix = Path(name).suffix.lower()
        if suffix and suffix not in SUPPORTED_EXTENSIONS:
            errors.append(UploadErrorOut(filename=name, detail=f"Unsupported file type: {suffix}"))
            continue

        try:
            chunks: list[bytes] = []
            size = 0
            chunk_size = 1024 * 1024
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise ValueError(f"File too large: {name}")
                chunks.append(chunk)
            data = b"".join(chunks)

            stored_path, local_path = await file_storage.save_upload(
                project_id=project.id,
                category=category.value,
                filename=name,
                data=data,
                content_type=upload.content_type,
            )
            text = extract_text_from_file(local_path, allow_ocr=allow_ocr)
            doc = Document(
                project_id=project.id,
                category=category,
                original_name=name,
                stored_path=stored_path,
                content_type=upload.content_type,
                size_bytes=size,
                extracted_text=text,
            )
            db.add(doc)
            saved.append(doc)
        except file_storage.StorageError as exc:
            errors.append(UploadErrorOut(filename=name, detail=str(exc)))
        except Exception as exc:  # noqa: BLE001 — keep batch going
            errors.append(UploadErrorOut(filename=name, detail=str(exc)))

    if not saved and errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "All uploads failed",
                "errors": [e.model_dump() for e in errors],
            },
        )

    await db.commit()
    for doc in saved:
        await db.refresh(doc)
    return UploadBatchOut(documents=[_doc_out(d) for d in saved], errors=errors)


@router.delete("/{project_id}/documents/{document_id}")
async def delete_document(
    project_id: int, document_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.project_id == project_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        await file_storage.delete_stored(doc.stored_path)
    except file_storage.StorageError:
        pass
    await db.delete(doc)
    await db.commit()
    return {"ok": True}


@router.post("/{project_id}/documents/{document_id}/reextract", response_model=DocumentOut)
async def reextract_document(
    project_id: int, document_id: int, db: AsyncSession = Depends(get_db)
) -> DocumentOut:
    """Re-run text/OCR extraction on an already stored file."""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.project_id == project_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        path = await file_storage.open_for_read(doc.stored_path)
    except file_storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    doc.extracted_text = extract_text_from_file(path)
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc)


@router.post("/{project_id}/analyze", response_model=AnalysisOut)
async def analyze_project(
    project_id: int,
    payload: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> AnalysisOut:
    project = await _get_project(db, project_id)
    report_language = (payload.report_language if payload and payload.report_language else None) or project.report_language

    docs_payload = [
        {
            "category": d.category,
            "original_name": d.original_name,
            "extracted_text": d.extracted_text or "",
        }
        for d in project.documents
    ]
    raw_type = getattr(project, "project_type", None)
    if isinstance(raw_type, ProjectType):
        ptype = raw_type
    elif raw_type:
        try:
            ptype = ProjectType(str(raw_type))
        except ValueError:
            ptype = ProjectType.INFRASTRUCTURE
    else:
        ptype = ProjectType.INFRASTRUCTURE

    result = await db.execute(select(ProjectStandard).where(ProjectStandard.project_id == project.id))
    std_rows = list(result.scalars().all())
    if not std_rows:
        std_rows = await ensure_project_standards(db, project, lang=project.ui_language.value)
    selected_standards = [
        {
            "code": r.standard_code,
            "title": r.title or r.standard_code,
            "standard_class": r.standard_class or "technical",
            "is_selected": bool(r.is_selected),
        }
        for r in std_rows
        if r.is_selected
    ]

    result = analyze_project_documents(
        country=project.country,
        report_language=report_language,
        documents=docs_payload,
        project_type=ptype,
        selected_standards=selected_standards,
    )

    analysis = Analysis(
        project_id=project.id,
        status="completed",
        summary=result["summary"],
        report_language=report_language,
        result_json=json.dumps(
            {
                "readiness_score": result["readiness_score"],
                "counts": result["counts"],
                "engine": result.get("engine"),
            },
            ensure_ascii=False,
        ),
    )
    db.add(analysis)
    await db.flush()

    for item in result["findings"]:
        db.add(
            Finding(
                analysis_id=analysis.id,
                code=item.code,
                category=item.category,
                severity=item.severity,
                title=item.title,
                description=item.description,
                recommendation=item.recommendation,
                financial_impact=item.financial_impact,
                schedule_impact=item.schedule_impact,
                evidence=item.evidence,
            )
        )

    await db.commit()
    return await _analysis_out(db, analysis.id)


@router.get("/{project_id}/analyses/latest", response_model=AnalysisOut)
async def latest_analysis(project_id: int, db: AsyncSession = Depends(get_db)) -> AnalysisOut:
    await _get_project(db, project_id)
    result = await db.execute(
        select(Analysis)
        .where(Analysis.project_id == project_id)
        .options(selectinload(Analysis.findings))
        .order_by(Analysis.id.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis yet")
    return _to_analysis_out(analysis)


async def _get_project(db: AsyncSession, project_id: int) -> Project:
    result = await db.execute(
        select(Project).options(selectinload(Project.documents)).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_project_meta(db: AsyncSession, project_id: int) -> Project:
    """Project row only — do not load documents (extracted_text can be huge)."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _analysis_out(db: AsyncSession, analysis_id: int) -> AnalysisOut:
    result = await db.execute(
        select(Analysis).options(selectinload(Analysis.findings)).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one()
    return _to_analysis_out(analysis)


def _to_analysis_out(analysis: Analysis) -> AnalysisOut:
    payload = json.loads(analysis.result_json or "{}")
    return AnalysisOut(
        id=analysis.id,
        project_id=analysis.project_id,
        status=analysis.status,
        summary=analysis.summary,
        report_language=analysis.report_language,
        readiness_score=payload.get("readiness_score", 0),
        counts=payload.get("counts", {"high": 0, "medium": 0, "low": 0, "total": 0}),
        findings=[FindingOut.model_validate(f) for f in analysis.findings],
        created_at=analysis.created_at,
    )
