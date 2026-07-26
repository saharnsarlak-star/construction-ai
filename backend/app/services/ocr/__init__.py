"""OCR package public API."""

from app.services.ocr.factory import get_ocr_service, ocr_runtime_status
from app.services.ocr.pipeline import extract_document
from app.services.ocr.types import DocumentExtractionResult, ExtractionPhase, OcrPageResult

__all__ = [
    "DocumentExtractionResult",
    "ExtractionPhase",
    "OcrPageResult",
    "extract_document",
    "get_ocr_service",
    "ocr_runtime_status",
]
