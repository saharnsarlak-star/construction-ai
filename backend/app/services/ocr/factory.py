"""Factory that returns the best available OCRService."""

from __future__ import annotations

from app.services.ocr.base import BaseOCRService
from app.services.ocr.providers.rapidocr_provider import RapidOCRService
from app.services.ocr.providers.tesseract_provider import TesseractOCRService

_cached: BaseOCRService | None = None


def get_ocr_service() -> BaseOCRService | None:
    """Prefer Tesseract (fa/de/en), else RapidOCR. None if nothing available."""
    global _cached
    if _cached is not None and _cached.available():
        return _cached
    for cls in (TesseractOCRService, RapidOCRService):
        svc = cls()
        if svc.available():
            _cached = svc
            return svc
    return None


def ocr_runtime_status() -> dict:
    tess = TesseractOCRService()
    rapid = RapidOCRService()
    active = get_ocr_service()
    return {
        "tesseract": tess.available(),
        "rapidocr": rapid.available(),
        "active": active.name if active else None,
        "available": active is not None,
    }
