"""Per-page PDF type detection (searchable vs scanned)."""

from __future__ import annotations

import re

from app.services.ocr.types import PdfPageKind

_MIN_SEARCHABLE_CHARS = 40


def classify_native_page_text(text: str | None) -> PdfPageKind:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) >= _MIN_SEARCHABLE_CHARS:
        return PdfPageKind.SEARCHABLE
    if cleaned:
        return PdfPageKind.MIXED
    return PdfPageKind.SCANNED


def classify_document(page_kinds: list[PdfPageKind]) -> str:
    if not page_kinds:
        return "empty"
    searchable = sum(1 for k in page_kinds if k == PdfPageKind.SEARCHABLE)
    scanned = sum(1 for k in page_kinds if k in (PdfPageKind.SCANNED, PdfPageKind.EMPTY))
    if searchable and scanned:
        return "mixed"
    if searchable:
        return "searchable"
    return "scanned"
