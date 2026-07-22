import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Analysis, Document, DocumentCategory, Finding, Project
from app.schemas import (
    AnalysisOut,
    AnalyzeRequest,
    DocumentOut,
    FindingOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from app.services.analyzer import analyze_project_documents
from app.services.extractor import SUPPORTED_EXTENSIONS, extract_text_from_file, has_usable_text
from app.services import storage as file_storage

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
    return ProjectOut(
        id=project.id,
        name=project.name,
        country=project.country,
        ui_language=project.ui_language,
        report_language=project.report_language,
        description=project.description,
        created_at=project.created_at,
        documents=[_doc_out(d) for d in project.documents],
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectOut]:
    result = await db.execute(select(Project).options(selectinload(Project.documents)).order_by(Project.id.desc()))
    return [_project_out(p) for p in result.scalars().all()]


@router.post("", response_model=ProjectOut)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    project = Project(**payload.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
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
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    project = await _get_project(db, project_id)
    return _project_out(project)


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    project = await _get_project(db, project_id)
    await db.delete(project)
    await db.commit()
    return {"ok": True}


@router.post("/{project_id}/documents", response_model=list[DocumentOut])
async def upload_documents(
    project_id: int,
    category: DocumentCategory = Form(...),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    project = await _get_project(db, project_id)
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    max_bytes = (
        None if settings.max_upload_mb <= 0 else settings.max_upload_mb * 1024 * 1024
    )
    saved: list[Document] = []

    for upload in files:
        name = upload.filename or "unnamed"
        suffix = Path(name).suffix.lower()
        if suffix and suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

        # Read in chunks to enforce size limit without holding extra copies longer than needed.
        chunks: list[bytes] = []
        size = 0
        chunk_size = 1024 * 1024
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise HTTPException(status_code=400, detail=f"File too large: {name}")
            chunks.append(chunk)
        data = b"".join(chunks)

        try:
            stored_path, local_path = await file_storage.save_upload(
                project_id=project.id,
                category=category.value,
                filename=name,
                data=data,
                content_type=upload.content_type,
            )
        except file_storage.StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        text = extract_text_from_file(local_path)
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

    await db.commit()
    for doc in saved:
        await db.refresh(doc)
    return [_doc_out(d) for d in saved]


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
    result = analyze_project_documents(
        country=project.country,
        report_language=report_language,
        documents=docs_payload,
    )

    analysis = Analysis(
        project_id=project.id,
        status="completed",
        summary=result["summary"],
        report_language=report_language,
        result_json=json.dumps(
            {"readiness_score": result["readiness_score"], "counts": result["counts"]},
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
