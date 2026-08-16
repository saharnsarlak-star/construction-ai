"""Load / extract text from admin catalog standard PDFs for analysis."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogStandardAsset
from app.services import storage as file_storage
from app.services.extractor import extract_document_full

logger = logging.getLogger(__name__)

# Full-volume Word/PDF standards can exceed 300k chars — avoid analyze-time truncation.
_MAX_CATALOG_TEXT = 500_000
_MAX_CATALOG_PAGES = 200


async def ensure_catalog_standard_text(
    db: AsyncSession,
    asset: CatalogStandardAsset,
    *,
    max_chars: int = _MAX_CATALOG_TEXT,
    force_refresh: bool = False,
) -> str:
    """Return cached extracted text for a catalog PDF, extracting once if needed."""
    existing = (getattr(asset, "extracted_text", None) or "").strip()
    if not force_refresh and len(existing) >= 40:
        if max_chars and len(existing) > max_chars:
            return existing[:max_chars]
        return existing

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


def catalog_asset_is_downloadable(asset: CatalogStandardAsset | None) -> bool:
    """True when a real uploaded file exists (not ingest placeholders)."""
    if asset is None:
        return False
    stored = (asset.stored_path or "").strip()
    if not stored or stored.startswith("manual/"):
        return False
    return (asset.size_bytes or 0) >= 64


async def extract_catalog_standard_text_background(asset_id: int) -> None:
    """Run text extraction outside the upload HTTP request."""
    from app.database import SessionLocal

    async with SessionLocal() as db:
        try:
            asset = await db.get(CatalogStandardAsset, asset_id)
            if asset is None:
                return
            await ensure_catalog_standard_text(db, asset)
            from app.services.standard_sections import warm_standard_sections_cache

            await warm_standard_sections_cache(db, standard_code=asset.standard_code)
        except Exception:  # noqa: BLE001
            logger.exception("background catalog extract failed asset_id=%s", asset_id)
