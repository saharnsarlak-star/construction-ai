"""Background document extraction jobs (async OCR pipeline)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.database import SessionLocal
from app.models import Document, DocumentCategory
from app.services import storage as file_storage
from app.services.extractor import extract_document_full, merge_extraction_meta
from app.services.ocr.types import ExtractionPhase

logger = logging.getLogger(__name__)


def _phase_percent(phase: ExtractionPhase, done: int, total: int) -> int:
    if phase == ExtractionPhase.COMPLETED:
        return 100
    if phase == ExtractionPhase.FAILED:
        return 0
    if total <= 0:
        return 5
    base = {
        ExtractionPhase.QUEUED: 0,
        ExtractionPhase.CONVERTING: 10,
        ExtractionPhase.OCR: 40,
        ExtractionPhase.EXTRACTING: 55,
        ExtractionPhase.MERGING: 90,
    }.get(phase, 20)
    span = 35
    return min(99, base + int(span * (done / max(total, 1))))


async def process_document_extraction(document_id: int) -> None:
    """Run full PDF pipeline for one document and persist text + page JSON."""
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if not doc:
            return

        def _set_progress(phase: ExtractionPhase, done: int, total: int, note: str | None) -> None:
            meta = {
                "extraction": {
                    "phase": phase.value,
                    "progressPercent": _phase_percent(phase, done, total),
                    "message": note,
                    "done": done,
                    "total": total,
                }
            }
            doc.meta_json = merge_extraction_meta(doc.meta_json, meta)

        try:
            _set_progress(ExtractionPhase.QUEUED, 0, 1, "Queued")
            await db.commit()

            path = await file_storage.open_for_read(doc.stored_path)
            treat_drawing = doc.category == DocumentCategory.DRAWING

            import asyncio

            def _run():
                return extract_document_full(
                    Path(path),
                    allow_ocr=True,
                    treat_as_drawing=treat_drawing,
                    on_progress=lambda phase, done, total, note: None,
                )

            # Progress updates inside thread are hard with async session; run then write final.
            # Intermediate phases written around the call for UI polling.
            _set_progress(ExtractionPhase.CONVERTING, 0, 1, "Converting pages…")
            await db.commit()

            result = await asyncio.to_thread(_run)

            doc.extracted_text = result.merged_text or doc.extracted_text
            meta = result.to_meta()
            meta["extraction"]["progressPercent"] = 100
            meta["extraction"]["message"] = "Completed"
            doc.meta_json = merge_extraction_meta(doc.meta_json, meta)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Extraction job failed for document %s", document_id)
            doc.meta_json = merge_extraction_meta(
                doc.meta_json,
                {
                    "extraction": {
                        "phase": ExtractionPhase.FAILED.value,
                        "progressPercent": 0,
                        "message": str(exc),
                        "error": str(exc),
                    }
                },
            )
            if not doc.extracted_text:
                doc.extracted_text = f"[EXTRACT_ERROR] {doc.original_name}: {exc}"
            await db.commit()


def queued_meta() -> str:
    return json.dumps(
        {
            "extraction": {
                "phase": ExtractionPhase.QUEUED.value,
                "progressPercent": 0,
                "message": "Uploading…",
            }
        },
        ensure_ascii=False,
    )
