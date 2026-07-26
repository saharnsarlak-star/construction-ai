"""Pluggable OCR / document-extraction types."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class PdfPageKind(str, Enum):
    SEARCHABLE = "searchable"
    SCANNED = "scanned"
    MIXED = "mixed"
    EMPTY = "empty"


class ExtractionPhase(str, Enum):
    QUEUED = "queued"
    CONVERTING = "converting"
    OCR = "ocr"
    EXTRACTING = "extracting"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class OcrPageResult:
    page: int
    text: str
    language: str = "en"
    confidence: float = 0.0
    contains_tables: bool = False
    contains_drawing: bool = False
    contains_stamp: bool = False
    contains_signature: bool = False
    needs_manual_review: bool = False
    source: str = "native"  # native | ocr | hybrid
    kind: str = PdfPageKind.SEARCHABLE.value
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "text": self.text,
            "language": self.language,
            "confidence": round(float(self.confidence), 2),
            "containsTables": self.contains_tables,
            "containsDrawing": self.contains_drawing,
            "containsStamp": self.contains_stamp,
            "containsSignature": self.contains_signature,
            "needsManualReview": self.needs_manual_review,
            "source": self.source,
            "kind": self.kind,
            "error": self.error,
        }


@dataclass
class DocumentExtractionResult:
    pages: list[OcrPageResult] = field(default_factory=list)
    merged_text: str = ""
    pdf_kind: str = "unknown"
    page_count: int = 0
    ocr_page_count: int = 0
    failed_pages: list[int] = field(default_factory=list)
    needs_manual_review: bool = False
    provider: str = "none"
    phase: str = ExtractionPhase.COMPLETED.value
    error: str | None = None
    extraction_method: str | None = None
    confidence_score: float | None = None
    structured: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        extraction: dict[str, Any] = {
            "phase": self.phase,
            "pdfKind": self.pdf_kind,
            "pageCount": self.page_count,
            "ocrPageCount": self.ocr_page_count,
            "failedPages": self.failed_pages,
            "needsManualReview": self.needs_manual_review,
            "provider": self.provider,
            "error": self.error,
            "progressPercent": 100 if self.phase == ExtractionPhase.COMPLETED.value else 0,
        }
        if self.extraction_method:
            extraction["method"] = self.extraction_method
        if self.confidence_score is not None:
            extraction["confidenceScore"] = round(float(self.confidence_score), 2)
        if self.structured is not None:
            extraction["structured"] = self.structured
        if self.notes:
            extraction["notes"] = self.notes
        return {
            "extraction": extraction,
            "pages": [p.to_json() for p in self.pages],
        }

    @staticmethod
    def from_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
        if not meta:
            return {}
        return meta.get("extraction") or {}
