"""Load / extract text from admin catalog standard PDFs for analysis."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogStandardAsset
from app.services import storage as file_storage
from app.services.extractor import extract_document_full

logger = logging.getLogger(__name__)

_MAX_CATALOG_TEXT = 80_000
_MAX_CATALOG_PAGES = 20


async def ensure_catalog_standard_text(
    db: AsyncSession,
    asset: CatalogStandardAsset,
    *,
    max_chars: int = _MAX_CATALOG_TEXT,
) -> str:
    """Return cached extracted text for a catalog PDF, extracting once if needed."""
    existing = (getattr(asset, "extracted_text", None) or "").strip()
    if len(existing) >= 40:
        return existing[:max_chars]

    try:
        path = await file_storage.open_for_read(asset.stored_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog standard open failed %s: %s", asset.standard_code, exc)
        asset.extraction_status = "failed"
        return ""

    import asyncio

    def _run() -> str:
        # Native text only, capped pages — OCR on multi-MB standards is too slow at analyze time.
        result = extract_document_full(
            Path(path),
            allow_ocr=False,
            treat_as_drawing=False,
            max_pages=_MAX_CATALOG_PAGES,
        )
        return (result.merged_text or "").strip()

    try:
        text = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog standard extract failed %s: %s", asset.standard_code, exc)
        asset.extraction_status = "failed"
        return ""

    text = (text or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    asset.extracted_text = text or None
    asset.extraction_status = "done" if text else "empty"
    try:
        await db.commit()
        await db.refresh(asset)
    except Exception:  # noqa: BLE001
        await db.rollback()
    return text
