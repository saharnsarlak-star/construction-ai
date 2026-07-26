"""OCR package public API (lazy imports so IFC/GAEB extractors need no OCR deps)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "DocumentExtractionResult",
    "ExtractionPhase",
    "OcrPageResult",
    "extract_document",
    "get_ocr_service",
    "ocr_runtime_status",
]


def __getattr__(name: str) -> Any:
    if name in {"DocumentExtractionResult", "ExtractionPhase", "OcrPageResult"}:
        from app.services.ocr import types as _types

        return getattr(_types, name)
    if name == "extract_document":
        from app.services.ocr.pipeline import extract_document as _extract_document

        return _extract_document
    if name in {"get_ocr_service", "ocr_runtime_status"}:
        from app.services.ocr import factory as _factory

        return getattr(_factory, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
