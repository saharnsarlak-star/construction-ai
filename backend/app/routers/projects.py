import json
import logging
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import Principal, get_principal
from app.config import settings
from app.database import get_db
from app.db_connect import is_transient_db_error, run_with_db_retry
from app.models import (
    Analysis,
    CatalogStandardAsset,
    Document,
    DocumentCategory,
    Finding,
    LanguageCode,
    Project,
    ProjectStandard,
    ProjectType,
)
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
    RelatedFindingsChain,
    RelatedFindingHop,
    UploadBatchOut,
    UploadErrorOut,
)
from app.services.analyzer import analyze_project_documents, enrich_findings_document_sources
from app.services.catalog_standard_text import catalog_asset_is_downloadable
from app.services.demo_limits import (
    assert_can_analyze,
    assert_can_create_project,
    assert_can_upload,
    record_demo_analysis,
)
from app.services.extractor import SUPPORTED_EXTENSIONS, extract_text_from_file, has_usable_text
from app.services.extraction_jobs import process_document_extraction, queued_meta
from app.services.rule_engine import run_python_seed_rules
from app.services.rule_engine.ai_engine import run_ai_hybrid_seed_rules
from app.services.finding_guardrail import apply_guardrails_to_findings
from app.services.knowledge_graph import build_chains_for_analysis
from app.services.standards_kg_bridge import link_project_standards_to_graph
from app.services import storage as file_storage
from app.services.project_standards import (
    ensure_project_standards,
    list_or_seed_project_standards,
    toggle_one_standard,
)

logger = logging.getLogger(__name__)

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


def _guess_taxonomy_code(filename: str, search_fn) -> str | None:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    hits = search_fn(stem, limit=1)
    return hits[0]["code"] if hits else None


def _doc_out(doc: Document) -> DocumentOut:
    from app.tender_taxonomy import get_entry

    text = doc.extracted_text or ""
    extra = _extraction_fields(doc)
    entry = get_entry(doc.taxonomy_code) if doc.taxonomy_code else None
    return DocumentOut(
        id=doc.id,
        category=doc.category,
        original_name=doc.original_name,
        taxonomy_code=doc.taxonomy_code,
        taxonomy_title_fa=entry.title_fa if entry else None,
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
        is_demo=bool(getattr(project, "is_demo", False)),
        created_at=project.created_at,
        documents=[_doc_out(d) for d in project.documents],
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[ProjectOut]:
    try:
        query = select(Project).options(selectinload(Project.documents)).order_by(Project.id.desc())
        if not principal.is_admin and principal.id is not None:
            # Seed "user" still sees legacy unowned projects; demo users only see their own.
            if principal.username == "user":
                query = query.where(
                    or_(Project.owner_user_id == principal.id, Project.owner_user_id.is_(None))
                )
            else:
                query = query.where(Project.owner_user_id == principal.id)
        result = await db.execute(query)
        return [_project_out(p) for p in result.scalars().all()]
    except Exception as exc:  # noqa: BLE001
        # Surface DB/schema errors to the client so CORS+500 is diagnosable.
        raise HTTPException(status_code=500, detail=f"list_projects failed: {exc}") from exc


@router.post("", response_model=ProjectOut)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ProjectOut:
    owner = None
    if principal.id is not None:
        from app.models import AppUser

        owner = await db.get(AppUser, principal.id)
        await assert_can_create_project(db, owner)
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
    if principal.id is not None:
        data["owner_user_id"] = principal.id
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


def _standard_out(
    row: ProjectStandard,
    lang: str = "fa",
    *,
    pdf_codes: set[str] | None = None,
) -> ProjectStandardOut:
    std = get_standard(row.standard_code)
    sclass = row.standard_class or (std.standard_class if std else "technical")
    if sclass == "contractual":
        check_target = "contract"
    elif sclass == "hybrid":
        check_target = "contract+technical"
    else:
        check_target = "drawings+boq+specifications"
    title = std.title_for(lang) if std else (row.title or row.standard_code)
    has_pdf = bool(pdf_codes and row.standard_code in pdf_codes)
    return ProjectStandardOut(
        standard_code=row.standard_code,
        title=title,
        standard_class=sclass,
        publisher=std.publisher if std else "",
        applicability_level=row.applicability_level or "optional",
        is_selected=bool(row.is_selected),
        selected_by=row.selected_by or "system_default",
        check_target=check_target,
        has_pdf=has_pdf,
    )


async def _catalog_pdf_codes(db: AsyncSession) -> set[str]:
    result = await db.execute(select(CatalogStandardAsset))
    return {
        asset.standard_code
        for asset in result.scalars().all()
        if catalog_asset_is_downloadable(asset)
    }


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
    pdf_codes = await _catalog_pdf_codes(db)
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            0 if r.is_selected else 1,
            0 if (r.applicability_level or "") == "mandatory_default" else 1,
            r.standard_code,
        ),
    )
    return [_standard_out(r, lang, pdf_codes=pdf_codes) for r in rows_sorted]


@router.put("/{project_id}/standards", response_model=list[ProjectStandardOut])
async def update_project_standards(
    project_id: int,
    payload: ProjectStandardsUpdate,
    db: AsyncSession = Depends(get_db),
) -> list[ProjectStandardOut]:
    """Fast path: toggle without loading project documents (avoids multi-second hangs)."""
    project = await _get_project_meta(db, project_id)
    lang = _project_lang(project)
    pdf_codes = await _catalog_pdf_codes(db)
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
            return [_standard_out(row, lang, pdf_codes=pdf_codes)]
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
            out.append(_standard_out(row, lang, pdf_codes=pdf_codes))
    return out


@router.post("/{project_id}/documents", response_model=UploadBatchOut)
async def upload_documents(
    project_id: int,
    category: Annotated[DocumentCategory, Form()],
    files: Annotated[list[UploadFile], File()],
    background_tasks: BackgroundTasks,
    taxonomy_code: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> UploadBatchOut:
    """
    Accept many files quickly. Text/OCR runs asynchronously via DocumentPipeline
    so scanned PDFs and drawings do not block the upload request.

    category=standard requires Admin. Prefer POST /api/standards/catalog for PDF retention.
    """
    if category == DocumentCategory.STANDARD and not principal.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Admin role required to upload standards. Users may only view/select and download PDFs.",
        )
    project = await run_with_db_retry(lambda: _get_project_meta(db, project_id))
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    from app.models import AppUser
    from app.services.demo_limits import is_demo_user
    from app.tender_taxonomy import get_entry, legacy_document_category, search_taxonomy

    resolved_taxonomy: str | None = None
    if taxonomy_code:
        code = taxonomy_code.strip()
        if not get_entry(code):
            raise HTTPException(status_code=400, detail=f"Unknown taxonomy code: {code}")
        resolved_taxonomy = code
        expected = legacy_document_category(code)
        if category != expected and category != DocumentCategory.TENDER:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Taxonomy {code} belongs under '{expected.value}' upload, "
                    f"not '{category.value}'."
                ),
            )

    owner = await db.get(AppUser, principal.id) if principal.id is not None else None
    if project.is_demo or is_demo_user(owner):
        await assert_can_upload(db, owner, project, incoming_files=len(files), incoming_bytes=0)

    max_bytes = (
        None if settings.max_upload_mb <= 0 else settings.max_upload_mb * 1024 * 1024
    )
    demo_file_cap = (
        settings.demo_max_file_mb * 1024 * 1024
        if (project.is_demo or is_demo_user(owner))
        else None
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
                if demo_file_cap is not None and size > demo_file_cap:
                    raise ValueError(
                        f"Demo limit: each file must be ≤ {settings.demo_max_file_mb} MB"
                    )
                chunks.append(chunk)
            data = b"".join(chunks)

            if project.is_demo or is_demo_user(owner):
                await assert_can_upload(db, owner, project, incoming_files=1, incoming_bytes=size)

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
                taxonomy_code=resolved_taxonomy or _guess_taxonomy_code(name, search_taxonomy),
                stored_path=stored_path,
                content_type=upload.content_type,
                size_bytes=size,
                extracted_text=text,
                meta_json=meta,
            )
            db.add(doc)
            saved.append(doc)
        except HTTPException:
            raise
        except file_storage.StorageError as exc:
            errors.append(UploadErrorOut(filename=name, detail=str(exc)))
        except Exception as exc:  # noqa: BLE001 — keep batch going
            errors.append(UploadErrorOut(filename=name, detail=str(exc) or exc.__class__.__name__))

    if not saved and errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "All uploads failed",
                "errors": [e.model_dump() for e in errors],
            },
        )

    async def _commit_batch() -> None:
        await db.commit()
        for doc in saved:
            await db.refresh(doc)

    try:
        await run_with_db_retry(_commit_batch)
    except Exception as exc:
        await db.rollback()
        for doc in saved:
            try:
                await file_storage.delete_stored(doc.stored_path)
            except Exception:  # noqa: BLE001
                pass
        if is_transient_db_error(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Database connection failed while saving files. "
                    "Please wait a few seconds and try again."
                ),
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Could not save uploaded files: {exc}",
        ) from exc

    for doc in saved:
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


_MAX_DOC_TEXT_FOR_ANALYSIS = 80_000
_EXTRACTION_WAIT_S = 20.0


def _slim_meta_for_analysis(meta_json: str | None) -> str | None:
    """Keep extraction status for gating; drop bulky per-page OCR text blobs."""
    if not meta_json:
        return None
    try:
        meta = json.loads(meta_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(meta, dict):
        return None
    extraction = meta.get("extraction") if isinstance(meta.get("extraction"), dict) else {}
    slim: dict = {
        "extraction": {
            k: extraction.get(k)
            for k in (
                "phase",
                "progressPercent",
                "message",
                "done",
                "total",
                "pdfKind",
                "pageCount",
                "ocrPageCount",
                "failedPages",
                "needsManualReview",
                "provider",
                "error",
            )
            if extraction.get(k) is not None
        }
    }
    pages = meta.get("pages") if isinstance(meta.get("pages"), list) else []
    if pages:
        slim["pages"] = [
            {
                "page": p.get("page"),
                "confidence": p.get("confidence"),
                "kind": p.get("kind"),
                "error": p.get("error"),
                "needsManualReview": p.get("needsManualReview"),
                "containsDrawing": p.get("containsDrawing"),
            }
            for p in pages[:40]
            if isinstance(p, dict)
        ]
    return json.dumps(slim, ensure_ascii=False)


@router.post("/{project_id}/analyze", response_model=AnalysisOut)
async def analyze_project(
    project_id: int,
    payload: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> AnalysisOut:
    import asyncio

    from app.models import AppUser

    project = await _get_project(db, project_id)
    owner = await db.get(AppUser, principal.id) if principal.id is not None else None
    owner = await assert_can_analyze(db, owner, project)
    report_language = (payload.report_language if payload and payload.report_language else None) or project.report_language
    # Keep project languages in sync with the language used for this analysis.
    if project.ui_language != report_language or project.report_language != report_language:
        project.ui_language = report_language
        project.report_language = report_language
        await db.commit()
        await db.refresh(project)

    # Before analysis: finish extraction for ANY document still empty/queued so
    # newly uploaded drawings/docs are included in this run (full re-analysis).
    pending_ids: list[int] = []
    for doc in project.documents:
        text = doc.extracted_text or ""
        phase = None
        if doc.meta_json:
            try:
                meta = json.loads(doc.meta_json)
                phase = (meta.get("extraction") or {}).get("phase")
            except json.JSONDecodeError:
                phase = None
        needs = False
        if phase in {"queued", "converting", "ocr", "extracting", "merging"}:
            needs = True
        elif phase is None and not (text or "").strip():
            # Never extracted yet
            needs = True
        # completed/failed drawings may legitimately have little text — do not re-OCR every analyze
        if needs:
            pending_ids.append(doc.id)

    for doc_id in pending_ids:
        try:
            await asyncio.wait_for(process_document_extraction(doc_id), timeout=_EXTRACTION_WAIT_S)
        except Exception:  # noqa: BLE001 — timeout or extract failure
            # Fall back to synchronous light extract so analysis still sees something.
            try:
                doc = next((d for d in project.documents if d.id == doc_id), None)
                if not doc:
                    continue
                path = await file_storage.open_for_read(doc.stored_path)
                if doc.category == DocumentCategory.DRAWING:
                    text = await asyncio.to_thread(
                        extract_text_from_file, path, allow_ocr=False, treat_as_drawing=True
                    )
                else:
                    text = await asyncio.to_thread(
                        extract_text_from_file, path, allow_ocr=False
                    )
                doc.extracted_text = text
                await db.commit()
            except Exception:  # noqa: BLE001
                continue

    if pending_ids:
        await db.commit()
        project = await _get_project(db, project_id)

    docs_payload = []
    for d in project.documents:
        text = d.extracted_text or ""
        if len(text) > _MAX_DOC_TEXT_FOR_ANALYSIS:
            text = text[:_MAX_DOC_TEXT_FOR_ANALYSIS]
        docs_payload.append(
            {
                "id": d.id,
                "category": d.category.value if hasattr(d.category, "value") else d.category,
                "original_name": d.original_name,
                "stored_path": d.stored_path,
                "extracted_text": text,
                "content_type": d.content_type,
                "meta_json": _slim_meta_for_analysis(d.meta_json),
            }
        )
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

    # Pull text from admin catalog PDFs so analysis actually uses uploaded standards.
    if selected_standards:
        from app.services.catalog_standard_text import ensure_catalog_standard_text

        codes = [s["code"] for s in selected_standards]
        assets = (
            await db.execute(
                select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code.in_(codes))
            )
        ).scalars().all()
        by_code = {a.standard_code: a for a in assets}
        for s in selected_standards:
            asset = by_code.get(s["code"])
            if asset is None:
                continue
            text = await ensure_catalog_standard_text(db, asset)
            if not text.strip():
                continue
            if len(text) > _MAX_DOC_TEXT_FOR_ANALYSIS:
                text = text[:_MAX_DOC_TEXT_FOR_ANALYSIS]
            s["extracted_text"] = text
            s["original_name"] = asset.original_name or s["title"]
            docs_payload.append(
                {
                    "id": -int(asset.id or 0) - 1,
                    "category": DocumentCategory.STANDARD.value,
                    "original_name": asset.original_name or s["code"],
                    "stored_path": asset.stored_path,
                    "extracted_text": text,
                    "content_type": asset.content_type,
                    "meta_json": json.dumps(
                        {
                            "extraction": {"phase": "completed", "provider": "catalog"},
                            "catalog_standard": True,
                            "standard_code": s["code"],
                        },
                        ensure_ascii=False,
                    ),
                }
            )

    result = await asyncio.to_thread(
        analyze_project_documents,
        country=project.country,
        report_language=report_language,
        documents=docs_payload,
        project_type=ptype,
        selected_standards=selected_standards,
        skip_keyword_standards=settings.ti_semantic_active,
    )

    # Phase 3/4 rule engines (default OFF). Keyword analyzer always runs first unchanged.
    rule_engine_count = 0
    ai_engine_count = 0
    ai_metrics: dict = {}
    if settings.new_rule_engine_enabled or settings.ai_rule_engine_enabled:
        element_payload: list[dict] = []
        try:
            from app.models import ElementDocumentRef, ProjectElement

            el_rows = (
                await db.execute(
                    select(ProjectElement).where(ProjectElement.project_id == project.id)
                )
            ).scalars().all()
            for el in el_rows:
                refs = (
                    await db.execute(
                        select(ElementDocumentRef).where(ElementDocumentRef.element_id == el.id)
                    )
                ).scalars().all()
                element_payload.append(
                    {
                        "id": el.id,
                        "element_type": el.element_type,
                        "name_label": el.name_label,
                        "type_mark": el.type_mark,
                        "ifc_global_id": el.ifc_global_id,
                        "match_key": el.match_key,
                        "document_ids": [r.document_id for r in refs],
                    }
                )
        except Exception:  # noqa: BLE001
            element_payload = []

        by_code = {f.code: f for f in result.get("findings") or []}

        rkb_catalog = None
        if settings.rkb_db_enabled:
            from app.knowledge.rkb import load_rkb_catalog_for_runners

            rkb_catalog = await load_rkb_catalog_for_runners(db)

        if settings.new_rule_engine_enabled:
            rule_findings = run_python_seed_rules(
                country=project.country,
                report_language=report_language,
                documents=docs_payload,
                project_type=ptype,
                selected_standards=selected_standards,
                elements=element_payload,
                project_id=project.id,
                rkb_catalog=rkb_catalog,
            )
            rule_engine_count = len(rule_findings)
            for rf in rule_findings:
                by_code[rf.code] = rf

        # Phase 4: AI / HYBRID. HYBRID python-detects first inside ai_engine, then LLM explains.
        if settings.ai_rule_engine_enabled:
            standard_req_payload: list[dict] = []
            if selected_standards:
                from app.standards_engine.ingestion.pipeline import load_requirements_for_standard

                for s in selected_standards:
                    code = str(s.get("code") or s.get("standard_code") or "").strip()
                    if not code or s.get("is_selected") is False:
                        continue
                    _, reqs = await load_requirements_for_standard(db, standard_code=code)
                    for r in reqs:
                        standard_req_payload.append(
                            {
                                **r,
                                "standard_code": code,
                                "text": r.get("requirement_text") or "",
                            }
                        )
            ai_findings, ai_metrics = run_ai_hybrid_seed_rules(
                country=project.country,
                report_language=report_language,
                documents=docs_payload,
                project_type=ptype,
                selected_standards=selected_standards,
                standard_requirements=standard_req_payload,
                elements=element_payload,
                project_id=project.id,
                rkb_catalog=rkb_catalog,
            )
            ai_engine_count = len(
                [f for f in ai_findings if f.code != "AI-LLM-NOT-CONFIGURED"]
            )
            for af in ai_findings:
                by_code[af.code] = af

        merged = list(by_code.values())
        merged = enrich_findings_document_sources(merged, docs_payload, lang=report_language)
        result["findings"] = merged
        risks = [f for f in merged if getattr(f, "finding_category", "risk") == "risk"]
        result["counts_risk"] = {
            "high": sum(1 for f in risks if f.severity.value == "high"),
            "medium": sum(1 for f in risks if f.severity.value == "medium"),
            "low": sum(1 for f in risks if f.severity.value == "low"),
            "total": len(risks),
        }
        engines = [result.get("engine") or "keyword"]
        if settings.new_rule_engine_enabled:
            engines.append("python_seed_rules")
        if settings.ai_rule_engine_enabled:
            engines.append("ai_hybrid_seed_rules")
        result["engine"] = "+".join(dict.fromkeys(str(e) for e in engines))

    # Phase 7 — Human Construction Experience (advisory; default OFF)
    experience_count = 0
    if settings.experience_layer_enabled:
        from app.services.experience_layer import match_experience_findings

        corpus_bits = [
            str(d.get("extracted_text") or "")
            for d in docs_payload
            if (d.get("extracted_text") or "").strip()
        ]
        exp_findings = await match_experience_findings(
            db,
            project_type=ptype,
            existing_findings=list(result.get("findings") or []),
            document_corpus="\n".join(corpus_bits)[:200_000],
            lang=report_language,
        )
        experience_count = len(exp_findings)
        if exp_findings:
            by_code_exp = {f.code: f for f in (result.get("findings") or [])}
            for ef in exp_findings:
                by_code_exp[ef.code] = ef
            merged_exp = list(by_code_exp.values())
            merged_exp = enrich_findings_document_sources(merged_exp, docs_payload, lang=report_language)
            result["findings"] = merged_exp
            engines = [result.get("engine") or "keyword"]
            engines.append("experience_layer")
            result["engine"] = "+".join(dict.fromkeys(str(e) for e in engines))
            # Experience findings are not mandatory risks — keep counts_risk on risk-only
            risks_only = [f for f in merged_exp if getattr(f, "finding_category", "risk") == "risk"]
            result["counts_risk"] = {
                "high": sum(1 for f in risks_only if f.severity.value == "high"),
                "medium": sum(1 for f in risks_only if f.severity.value == "medium"),
                "low": sum(1 for f in risks_only if f.severity.value == "low"),
                "total": len(risks_only),
            }
            result["counts_experience"] = experience_count

    # TI-1 — Semantic standards compliance / silence detection (Phase C)
    ti_count = 0
    ti_metrics: dict = {}
    ti_findings_pending: list = []
    if settings.ti_semantic_active:
        from app.services.tender_intelligence import run_semantic_standards_compliance

        ti_corpus_bits = [
            str(d.get("extracted_text") or "")
            for d in docs_payload
            if (d.get("extracted_text") or "").strip()
        ]
        ti_std_codes = [
            str(s.get("code") or s.get("standard_code") or "").strip()
            for s in (selected_standards or [])
            if str(s.get("code") or s.get("standard_code") or "").strip()
        ]
        ti_findings, ti_metrics = await run_semantic_standards_compliance(
            db,
            project_id=project.id,
            selected_standard_codes=ti_std_codes,
            document_corpus="\n".join(ti_corpus_bits)[:200_000],
            lang=report_language,
        )
        ti_findings_pending = [
            f for f in ti_findings if f.code != "TI-LLM-NOT-CONFIGURED"
        ]
        ti_count = len(
            [f for f in ti_findings_pending if getattr(f, "finding_category", "risk") == "risk"]
        )
        if ti_findings:
            by_code_ti = {f.code: f for f in (result.get("findings") or [])}
            for tf in ti_findings:
                by_code_ti[tf.code] = tf
            merged_ti = list(by_code_ti.values())
            merged_ti = enrich_findings_document_sources(merged_ti, docs_payload, lang=report_language)
            result["findings"] = merged_ti
            engines = [result.get("engine") or "keyword"]
            engines.append("tender_intelligence")
            result["engine"] = "+".join(dict.fromkeys(str(e) for e in engines))
            risks_only = [
                f for f in merged_ti if getattr(f, "finding_category", "risk") == "risk"
            ]
            result["counts_risk"] = {
                "high": sum(1 for f in risks_only if f.severity.value == "high"),
                "medium": sum(1 for f in risks_only if f.severity.value == "medium"),
                "low": sum(1 for f in risks_only if f.severity.value == "low"),
                "total": len(risks_only),
            }

    # Phase 8 — Vision drawing checks (DRAW-SEED-002..004); default OFF
    vision_count = 0
    vision_metrics: dict = {}
    if settings.vision_drawing_checks_enabled:
        from app.services.vision_drawing_checks import run_vision_drawing_checks

        drawing_docs = [
            d
            for d in docs_payload
            if str(d.get("category") or "").lower() in {"drawing", DocumentCategory.DRAWING.value}
        ]
        vision_findings, vision_metrics = run_vision_drawing_checks(
            drawing_docs=drawing_docs,
            report_language=report_language,
            max_pages_per_doc=max(1, int(settings.vision_max_pages_per_doc or 2)),
        )
        vision_count = len(vision_findings)
        if vision_findings:
            by_code_v = {f.code: f for f in (result.get("findings") or [])}
            for vf in vision_findings:
                by_code_v[vf.code] = vf
            result["findings"] = list(by_code_v.values())
            engines = [result.get("engine") or "keyword"]
            engines.append("vision_drawing")
            result["engine"] = "+".join(dict.fromkeys(str(e) for e in engines))
            risks_only = [
                f for f in result["findings"] if getattr(f, "finding_category", "risk") == "risk"
            ]
            result["counts_risk"] = {
                "high": sum(1 for f in risks_only if f.severity.value == "high"),
                "medium": sum(1 for f in risks_only if f.severity.value == "medium"),
                "low": sum(1 for f in risks_only if f.severity.value == "low"),
                "total": len(risks_only),
            }

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
                "counts_experience": result.get("counts_experience") or experience_count,
                "counts_vision": vision_count,
                "aggregate_risk_score": result.get("aggregate_risk_score"),
                "documents_with_limitations": result.get("documents_with_limitations"),
                "text_extraction_success_rate": result.get("text_extraction_success_rate"),
                "engine": result.get("engine"),
                "python_rule_findings": rule_engine_count,
                "ai_rule_findings": ai_engine_count,
                "experience_findings": experience_count,
                "tender_intelligence_findings": ti_count,
                "tender_intelligence_metrics": ti_metrics,
                "vision_findings": vision_count,
                "vision_metrics": vision_metrics,
                "ai_metrics": ai_metrics,
                "analyzed_document_ids": sorted(
                    int(d["id"]) for d in docs_payload if d.get("id") is not None
                ),
                "analyzed_document_count": len(docs_payload),
                "prepared_extractions": len(pending_ids),
            },
            ensure_ascii=False,
        ),
    )
    db.add(analysis)
    await db.flush()

    # Part 5 evidence guardrail — downgrade Med/High without evidence before persist.
    guardrail_events: list = []
    try:
        findings_for_guardrail = list(result.get("findings") or [])
        guarded, guardrail_events = apply_guardrails_to_findings(findings_for_guardrail)
        result["findings"] = guarded
        if guardrail_events:
            risks_only = [f for f in guarded if getattr(f, "finding_category", "risk") == "risk"]
            result["counts_risk"] = {
                "high": sum(1 for f in risks_only if f.severity.value == "high"),
                "medium": sum(1 for f in risks_only if f.severity.value == "medium"),
                "low": sum(1 for f in risks_only if f.severity.value == "low"),
                "total": len(risks_only),
            }
    except Exception:  # noqa: BLE001
        logger.exception("Finding guardrail failed for project %s", project.id)

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
                source_layer=getattr(item, "source_layer", None),
                confidence_score=getattr(item, "confidence_score", None),
                source_document_name=getattr(item, "source_document_name", None),
                source_page=getattr(item, "source_page", None),
            )
        )

    # TI-1 graph edges: Finding → StandardClause (gaps / conflicts_with)
    if settings.knowledge_graph_enabled and ti_findings_pending:
        try:
            from app.services.tender_intelligence import link_ti_findings_to_graph

            await db.flush()
            persisted = (
                await db.execute(select(Finding).where(Finding.analysis_id == analysis.id))
            ).scalars().all()
            ti_linked = await link_ti_findings_to_graph(
                db,
                project_id=project.id,
                finding_rows=persisted,
                ti_findings=ti_findings_pending,
                document_id=next(
                    (int(d["id"]) for d in docs_payload if d.get("id") is not None and str(d.get("category", "")).lower() == "tender"),
                    None,
                ),
            )
            if ti_metrics is not None:
                ti_metrics["graph_edges_linked"] = ti_linked
        except Exception:  # noqa: BLE001
            logger.exception("TI-1 graph linking failed for analysis %s", analysis.id)

    # Phase 5: Knowledge Graph risk chains (additive; default OFF)
    related_chains: list = []
    kg_stats: dict = {}
    if settings.knowledge_graph_enabled:
        try:
            await db.flush()
            if settings.ontology_enabled:
                std_kg = await link_project_standards_to_graph(
                    db, project_id=project.id
                )
                kg_stats["standards_bridge"] = std_kg
            kg_payload = await build_chains_for_analysis(
                db,
                project_id=project.id,
                analysis_id=analysis.id,
                documents=list(project.documents),
            )
            related_chains = kg_payload.get("related_findings_chain") or []
            kg_stats = kg_payload.get("link_stats") or {}
            # Persist chains on analysis result_json without touching Finding rows
            payload = json.loads(analysis.result_json or "{}")
            payload["related_findings_chain"] = related_chains
            payload["knowledge_graph"] = {
                "enabled": True,
                "chain_count": len(related_chains),
                "link_stats": kg_stats,
                "guardrail_events": guardrail_events,
            }
            engines = str(payload.get("engine") or "keyword")
            if "knowledge_graph" not in engines:
                payload["engine"] = f"{engines}+knowledge_graph"
            analysis.result_json = json.dumps(payload, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            logger = __import__("logging").getLogger(__name__)
            logger.exception("Knowledge graph chain build failed for analysis %s", analysis.id)

    await db.commit()
    await record_demo_analysis(db, owner)
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
    return await _analysis_out(db, analysis.id)


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
    docs_payload: list[dict] = []
    try:
        proj = await _get_project(db, analysis.project_id)
        docs_payload = [
            {
                "original_name": d.original_name,
                "category": d.category.value if hasattr(d.category, "value") else str(d.category),
                "extracted_text": d.extracted_text or "",
            }
            for d in (proj.documents or [])
        ]
    except Exception:  # noqa: BLE001
        docs_payload = []
    return _to_analysis_out(analysis, documents=docs_payload)


def _to_analysis_out(analysis: Analysis, *, documents: list[dict] | None = None) -> AnalysisOut:
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
        doc_name = getattr(f, "source_document_name", None)
        page = getattr(f, "source_page", None)
        excerpt = getattr(f, "source_excerpt", None)
        if not doc_name or page is None:
            for step in chain:
                if not doc_name and step.startswith("document="):
                    doc_name = step.split("=", 1)[1].strip() or None
                if page is None and step.startswith("location="):
                    from app.services.analyzer import parse_source_page

                    page = parse_source_page(step.split("=", 1)[1])
        if not doc_name and f.evidence:
            m = re.search(r"^\s*\(([^)]+)\)|\b([^\s:]+\.(?:pdf|docx?|xlsx?|txt))\b", f.evidence, re.I)
            if m:
                doc_name = (m.group(1) or m.group(2) or "").strip() or None
        if documents and (not doc_name or page is None or not excerpt):
            from app.services.analyzer import find_page_for_quote, locate_document_excerpt

            hints = re.findall(
                r"[\w\u0600-\u06FFA-Za-z]{3,}",
                f"{f.title or ''} {excerpt or ''} {f.description or ''}",
            )[:16]
            if not doc_name or not excerpt:
                name, found_excerpt, found_page = locate_document_excerpt(
                    documents,
                    keywords=hints,
                    prefer_categories=("tender",),
                )
                if not doc_name and name:
                    doc_name = name
                if not excerpt and found_excerpt:
                    excerpt = found_excerpt
                if page is None and found_page is not None:
                    page = found_page
            if page is None:
                page = find_page_for_quote(
                    documents,
                    filename=doc_name,
                    quote=excerpt,
                    keywords=hints,
                )
        if excerpt:
            # Make quotes readable: NFKC + repair only truly reversed Persian.
            from app.services.extractor import clean_display_excerpt

            excerpt = clean_display_excerpt(excerpt, max_len=800) or excerpt
            # If stored quote is still unusable, re-cut a sentence from the source file.
            from app.services.extractor import _fa_token_score, _looks_visually_reversed

            if documents and (
                _looks_visually_reversed(excerpt)
                or (_fa_token_score(excerpt) < 2 and re.search(r"[\u0600-\u06FF]", excerpt or ""))
            ):
                from app.services.analyzer import locate_document_excerpt

                hints = re.findall(
                    r"[\w\u0600-\u06FFA-Za-z]{3,}",
                    f"{f.title or ''} {f.description or ''}",
                )[:12]
                prefer = ("tender",)
                name, found_excerpt, found_page = locate_document_excerpt(
                    documents,
                    keywords=hints,
                    prefer_categories=prefer,
                )
                if found_excerpt:
                    excerpt = clean_display_excerpt(found_excerpt, max_len=800) or found_excerpt
                    if not doc_name and name:
                        doc_name = name
                    if page is None and found_page is not None:
                        page = found_page
        # Keep human-readable cause steps only (hide metadata dumps)
        display_chain = [
            s
            for s in chain
            if s.strip()
            and not re.match(
                r"^(risk_id|check|source_layer|rkb_source|confidence_score|document|location|score_model)=",
                s.strip(),
            )
        ]
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
                source_excerpt=excerpt,
                cause_effect_chain=display_chain,
                data_completeness_caveat=getattr(f, "data_completeness_caveat", None),
                estimated_impact=getattr(f, "estimated_impact", None),
                source_layer=getattr(f, "source_layer", None),
                confidence_score=getattr(f, "confidence_score", None),
                source_document_name=doc_name,
                source_page=page,
            )
        )
    counts = payload.get("counts_risk") or payload.get("counts") or {
        "high": 0,
        "medium": 0,
        "low": 0,
        "total": 0,
    }
    counts_all = payload.get("counts") or counts
    raw_chains = payload.get("related_findings_chain") or []
    chains_out: list[RelatedFindingsChain] = []
    for c in raw_chains:
        if not isinstance(c, dict):
            continue
        hops = []
        for h in c.get("related_findings") or []:
            if not isinstance(h, dict):
                continue
            hops.append(
                RelatedFindingHop(
                    finding_id=int(h.get("finding_id") or 0),
                    code=str(h.get("code") or ""),
                    title=str(h.get("title") or ""),
                    severity=h.get("severity"),
                    via_element_id=h.get("via_element_id"),
                    path=list(h.get("path") or []),
                    path_summary=str(h.get("path_summary") or ""),
                )
            )
        chains_out.append(
            RelatedFindingsChain(
                anchor_finding_id=int(c.get("anchor_finding_id") or 0),
                anchor_finding_code=str(c.get("anchor_finding_code") or ""),
                anchor_title=c.get("anchor_title"),
                shared_element=dict(c.get("shared_element") or {}),
                documents=list(c.get("documents") or []),
                related_findings=hops,
                hop_count=int(c.get("hop_count") or len(hops)),
                narrative=str(c.get("narrative") or ""),
            )
        )
    return AnalysisOut(
        id=analysis.id,
        project_id=analysis.project_id,
        status=analysis.status,
        summary=analysis.summary,
        report_language=analysis.report_language,
        readiness_score=payload.get("readiness_score", 0),
        counts=counts_all,
        counts_risk=counts,
        counts_experience=payload.get("counts_experience"),
        aggregate_risk_score=payload.get("aggregate_risk_score"),
        documents_with_limitations=payload.get("documents_with_limitations"),
        text_extraction_success_rate=payload.get("text_extraction_success_rate"),
        findings=findings_out,
        related_findings_chain=chains_out,
        engine=payload.get("engine"),
        python_rule_findings=payload.get("python_rule_findings"),
        ai_rule_findings=payload.get("ai_rule_findings"),
        tender_intelligence_findings=payload.get("tender_intelligence_findings"),
        experience_findings=payload.get("experience_findings"),
        vision_findings=payload.get("vision_findings"),
        ai_metrics=payload.get("ai_metrics"),
        tender_intelligence_metrics=payload.get("tender_intelligence_metrics"),
        created_at=analysis.created_at,
    )
