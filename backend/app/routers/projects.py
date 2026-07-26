import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Analysis, Document, DocumentCategory, Finding, LanguageCode, Project, ProjectStandard, ProjectType
from app.schemas import (
    AnalysisOut,
    AnalyzeRequest,
    DocumentBulkDelete,
    DocumentBulkDeleteOut,
    BulkDeleteItemResult,
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
from app.services.extraction_jobs import process_document_extraction, queued_meta
from app.services import storage as file_storage
from app.services.project_standards import (
    ensure_project_standards,
    list_or_seed_project_standards,
    toggle_one_standard,
)
from app.knowledge.country_profiles import get_country_profile
from app.knowledge.standards_catalog import get_standard

router = APIRouter(prefix="/projects", tags=["projects"])


def _extraction_fields(doc: Document) -> dict:
    phase = None
    progress = None
    message = None
    needs_review = False
    if doc.meta_json:
        try:
            meta = json.loads(doc.meta_json)
            ex = meta.get("extraction") or {}
            phase = ex.get("phase")
            progress = ex.get("progressPercent")
            message = ex.get("message")
            needs_review = bool(ex.get("needsManualReview"))
            if not needs_review:
                pages = meta.get("pages") or []
                needs_review = any(p.get("needsManualReview") for p in pages if isinstance(p, dict))
        except json.JSONDecodeError:
            pass
    return {
        "extraction_phase": phase,
        "extraction_progress": progress,
        "extraction_message": message,
        "needs_manual_review": needs_review,
    }


def _doc_out(doc: Document) -> DocumentOut:
    text = doc.extracted_text or ""
    extra = _extraction_fields(doc)
    return DocumentOut(
        id=doc.id,
        category=doc.category,
        original_name=doc.original_name,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        has_text=has_usable_text(text),
        ocr_applied=text.lstrip().startswith("[OCR_APPLIED]")
        or "(ocr" in text.lower()
        or (extra.get("extraction_phase") == "completed" and "ocr" in (text[:200].lower())),
        created_at=doc.created_at,
        **extra,
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
    # One app language: keep UI and report language identical.
    lang = data.get("report_language") or data.get("ui_language") or LanguageCode.FA
    data["ui_language"] = lang
    data["report_language"] = lang
    profile = get_country_profile(payload.country)
    data["country_profile_code"] = profile.code
    # DB column is varchar
    if hasattr(data.get("project_type"), "value"):
        data["project_type"] = data["project_type"].value
    project = Project(**data)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    lang_value = lang.value if hasattr(lang, "value") else str(lang)
    await ensure_project_standards(db, project, lang=lang_value)
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
    language_changed = False
    updates = payload.model_dump(exclude_unset=True)
    # Keep UI + report language identical whenever either is sent.
    if "ui_language" in updates or "report_language" in updates:
        lang = updates.get("report_language") or updates.get("ui_language")
        updates["ui_language"] = lang
        updates["report_language"] = lang
        if lang is not None and (
            project.ui_language != lang or project.report_language != lang
        ):
            language_changed = True
    for key, value in updates.items():
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
    if country_or_type_changed or language_changed:
        lang_value = (
            project.report_language.value
            if hasattr(project.report_language, "value")
            else str(project.report_language)
        )
        await ensure_project_standards(db, project, lang=lang_value)
    return _project_out(project)


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    project = await _get_project(db, project_id)
    await db.delete(project)
    await db.commit()
    return {"ok": True}


def _standard_out(row: ProjectStandard, lang: str = "fa") -> ProjectStandardOut:
    std = get_standard(row.standard_code)
    sclass = row.standard_class or (std.standard_class if std else "technical")
    if sclass == "contractual":
        check_target = "contract"
    elif sclass == "hybrid":
        check_target = "contract+technical"
    else:
        check_target = "drawings+boq+specifications"
    title = std.title_for(lang) if std else (row.title or row.standard_code)
    return ProjectStandardOut(
        standard_code=row.standard_code,
        title=title,
        standard_class=sclass,
        publisher=std.publisher if std else "",
        applicability_level=row.applicability_level or "optional",
        is_selected=bool(row.is_selected),
        selected_by=row.selected_by or "system_default",
        check_target=check_target,
    )


def _project_lang(project: Project) -> str:
    lang = project.report_language or project.ui_language
    return lang.value if hasattr(lang, "value") else str(lang)


@router.get("/{project_id}/standards", response_model=list[ProjectStandardOut])
async def list_project_standards(
    project_id: int, db: AsyncSession = Depends(get_db)
) -> list[ProjectStandardOut]:
    project = await _get_project_meta(db, project_id)
    lang = _project_lang(project)
    rows = await list_or_seed_project_standards(db, project, lang=lang)
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            0 if r.is_selected else 1,
            0 if (r.applicability_level or "") == "mandatory_default" else 1,
            r.standard_code,
        ),
    )
    return [_standard_out(r, lang) for r in rows_sorted]


@router.put("/{project_id}/standards", response_model=list[ProjectStandardOut])
async def update_project_standards(
    project_id: int,
    payload: ProjectStandardsUpdate,
    db: AsyncSession = Depends(get_db),
) -> list[ProjectStandardOut]:
    """Fast path: toggle without loading project documents (avoids multi-second hangs)."""
    project = await _get_project_meta(db, project_id)
    lang = _project_lang(project)
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
            return [_standard_out(row, lang)]
    # Fallback: seed then toggle
    rows = await list_or_seed_project_standards(db, project, lang=lang)
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
            out.append(_standard_out(row, lang))
    return out


@router.post("/{project_id}/documents", response_model=UploadBatchOut)
async def upload_documents(
    project_id: int,
    category: Annotated[DocumentCategory, Form()],
    files: Annotated[list[UploadFile], File()],
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> UploadBatchOut:
    """
    Accept many files quickly. Text/OCR runs asynchronously via DocumentPipeline
    so scanned PDFs and drawings do not block the upload request.
    """
    project = await _get_project(db, project_id)
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    max_bytes = (
        None if settings.max_upload_mb <= 0 else settings.max_upload_mb * 1024 * 1024
    )
    saved: list[Document] = []
    errors: list[UploadErrorOut] = []
    extract_ids: list[int] = []

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
            # Fast path for tiny text files; PDFs/images go async OCR pipeline.
            if suffix in {".txt", ".csv"}:
                text = local_path.read_text(encoding="utf-8", errors="ignore")
                meta = None
            else:
                text = ""
                meta = queued_meta()

            doc = Document(
                project_id=project.id,
                category=category,
                original_name=name,
                stored_path=stored_path,
                content_type=upload.content_type,
                size_bytes=size,
                extracted_text=text,
                meta_json=meta,
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
        if doc.meta_json and '"queued"' in doc.meta_json:
            extract_ids.append(doc.id)

    for doc_id in extract_ids:
        background_tasks.add_task(process_document_extraction, doc_id)

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


@router.post("/{project_id}/documents/bulk-delete", response_model=DocumentBulkDeleteOut)
async def bulk_delete_documents(
    project_id: int,
    payload: DocumentBulkDelete,
    db: AsyncSession = Depends(get_db),
) -> DocumentBulkDeleteOut:
    """
    Delete many documents in one request, scoped to this project only.

    Findings do not FK to documents; we treat a file as "referenced" when its
    original_name appears in any finding evidence/source_excerpt/description
    for this project's analyses.

    Safer default: block referenced files unless force=true.
    When force=true, files are deleted and historical findings are kept as-is
    (source file was later removed).
    """
    await _get_project_meta(db, project_id)
    ids = list(dict.fromkeys(payload.document_ids))

    result = await db.execute(
        select(Document).where(Document.project_id == project_id, Document.id.in_(ids))
    )
    found = {d.id: d for d in result.scalars().all()}

    referenced_names: set[str] = set()
    try:
        findings_q = await db.execute(
            select(Finding.evidence, Finding.source_excerpt, Finding.description)
            .join(Analysis, Analysis.id == Finding.analysis_id)
            .where(Analysis.project_id == project_id)
        )
        for evidence, excerpt, description in findings_q.all():
            blob = " ".join(x for x in (evidence, excerpt, description) if x)
            if blob:
                referenced_names.add(blob)
    except Exception:  # noqa: BLE001
        referenced_names = set()

    def _is_referenced(name: str) -> bool:
        if not name or not referenced_names:
            return False
        return any(name in blob for blob in referenced_names)

    results: list[BulkDeleteItemResult] = []
    deleted_count = 0

    for doc_id in ids:
        doc = found.get(doc_id)
        if not doc:
            results.append(
                BulkDeleteItemResult(
                    document_id=doc_id,
                    original_name=None,
                    status="not_found",
                    detail="File not found in this project",
                )
            )
            continue

        name = doc.original_name or ""
        if not payload.force and _is_referenced(name):
            results.append(
                BulkDeleteItemResult(
                    document_id=doc.id,
                    original_name=name,
                    status="blocked_referenced",
                    detail=(
                        "This file appears in a previous analysis finding. "
                        "Deleting it may invalidate existing references. "
                        "Retry with force=true to delete anyway; findings are kept."
                    ),
                )
            )
            continue

        try:
            try:
                await file_storage.delete_stored(doc.stored_path)
            except file_storage.StorageError:
                pass
            await db.delete(doc)
            deleted_count += 1
            results.append(
                BulkDeleteItemResult(
                    document_id=doc.id,
                    original_name=name,
                    status="deleted",
                    detail=None,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                BulkDeleteItemResult(
                    document_id=doc.id,
                    original_name=name,
                    status="error",
                    detail=str(exc),
                )
            )

    await db.commit()
    failed_count = sum(1 for r in results if r.status != "deleted")
    return DocumentBulkDeleteOut(
        deleted_count=deleted_count,
        failed_count=failed_count,
        results=results,
    )


@router.post("/{project_id}/documents/{document_id}/reextract", response_model=DocumentOut)
async def reextract_document(
    project_id: int,
    document_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    """Queue full detect→OCR→merge pipeline again for one document."""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.project_id == project_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.meta_json = queued_meta()
    doc.extracted_text = ""
    await db.commit()
    await db.refresh(doc)
    background_tasks.add_task(process_document_extraction, doc.id)
    return _doc_out(doc)


@router.post("/{project_id}/analyze", response_model=AnalysisOut)
async def analyze_project(
    project_id: int,
    payload: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> AnalysisOut:
    import asyncio

    project = await _get_project(db, project_id)
    report_language = (payload.report_language if payload and payload.report_language else None) or project.report_language
    # Keep project languages in sync with the language used for this analysis.
    if project.ui_language != report_language or project.report_language != report_language:
        project.ui_language = report_language
        project.report_language = report_language
        await db.commit()
        await db.refresh(project)

    # Before analysis: OCR any tender/schedule/standard that still lacks usable text.
    # Drawings: run CAD extract (DWG/DXF/Revit) when still empty — do not OCR CAD binaries.
    refreshed = 0
    for doc in project.documents:
        if refreshed >= 12:
            break
        if has_usable_text(doc.extracted_text or ""):
            continue
        try:
            path = await file_storage.open_for_read(doc.stored_path)
            if doc.category == DocumentCategory.DRAWING:
                text = await asyncio.to_thread(
                    extract_text_from_file, path, allow_ocr=False, treat_as_drawing=True
                )
            else:
                text = await asyncio.to_thread(
                    extract_text_from_file, path, allow_ocr=True
                )
            doc.extracted_text = text
            refreshed += 1
        except Exception:  # noqa: BLE001
            continue
    if refreshed:
        await db.commit()
        await db.refresh(project)
        # reload documents after commit
        project = await _get_project(db, project_id)

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
    report_lang_value = (
        report_language.value if hasattr(report_language, "value") else str(report_language)
    )
    std_rows = await ensure_project_standards(db, project, lang=report_lang_value)
    selected_standards = []
    for r in std_rows:
        if not r.is_selected:
            continue
        std = get_standard(r.standard_code)
        title = std.title_for(report_lang_value) if std else (r.title or r.standard_code)
        selected_standards.append(
            {
                "code": r.standard_code,
                "title": title,
                "standard_class": r.standard_class or "technical",
                "is_selected": True,
            }
        )

    result = analyze_project_documents(
        country=project.country,
        report_language=report_language,
        documents=docs_payload,
        project_type=ptype,
        selected_standards=selected_standards,
    )

    analysis = Analysis(
        project_id=project.id,
        status=result.get("analysis_status") or "completed",
        summary=result["summary"],
        report_language=report_language,
        result_json=json.dumps(
            {
                "readiness_score": result["readiness_score"],
                "counts": result["counts"],
                "counts_risk": result.get("counts_risk") or result["counts"],
                "aggregate_risk_score": result.get("aggregate_risk_score"),
                "documents_with_limitations": result.get("documents_with_limitations"),
                "text_extraction_success_rate": result.get("text_extraction_success_rate"),
                "engine": result.get("engine"),
            },
            ensure_ascii=False,
        ),
    )
    db.add(analysis)
    await db.flush()

    seen_codes: set[str] = set()
    for item in result["findings"]:
        if item.code in seen_codes:
            continue
        seen_codes.add(item.code)
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
                finding_category=getattr(item, "finding_category", None) or "risk",
                risk_score=getattr(item, "risk_score", None),
                source_excerpt=getattr(item, "source_excerpt", None) or item.evidence,
                cause_effect_json=json.dumps(
                    getattr(item, "cause_effect_chain", None) or [], ensure_ascii=False
                ),
                data_completeness_caveat=getattr(item, "data_completeness_caveat", None),
                estimated_impact=getattr(item, "estimated_impact", None),
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
    findings_out: list[FindingOut] = []
    seen_ids: set[int] = set()
    for f in analysis.findings:
        if f.id in seen_ids:
            continue
        seen_ids.add(f.id)
        chain: list[str] = []
        raw_chain = getattr(f, "cause_effect_json", None)
        if raw_chain:
            try:
                parsed = json.loads(raw_chain)
                if isinstance(parsed, list):
                    chain = [str(x) for x in parsed]
            except json.JSONDecodeError:
                chain = []
        findings_out.append(
            FindingOut(
                id=f.id,
                code=f.code,
                category=f.category,
                severity=f.severity,
                title=f.title,
                description=f.description,
                recommendation=f.recommendation,
                financial_impact=f.financial_impact,
                schedule_impact=f.schedule_impact,
                evidence=f.evidence,
                finding_category=getattr(f, "finding_category", None) or "risk",
                risk_score=getattr(f, "risk_score", None),
                source_excerpt=getattr(f, "source_excerpt", None),
                cause_effect_chain=chain,
                data_completeness_caveat=getattr(f, "data_completeness_caveat", None),
                estimated_impact=getattr(f, "estimated_impact", None),
            )
        )
    counts = payload.get("counts_risk") or payload.get("counts") or {
        "high": 0,
        "medium": 0,
        "low": 0,
        "total": 0,
    }
    return AnalysisOut(
        id=analysis.id,
        project_id=analysis.project_id,
        status=analysis.status,
        summary=analysis.summary,
        report_language=analysis.report_language,
        readiness_score=payload.get("readiness_score", 0),
        counts=counts,
        counts_risk=counts,
        aggregate_risk_score=payload.get("aggregate_risk_score"),
        documents_with_limitations=payload.get("documents_with_limitations"),
        text_extraction_success_rate=payload.get("text_extraction_success_rate"),
        findings=findings_out,
        created_at=analysis.created_at,
    )
