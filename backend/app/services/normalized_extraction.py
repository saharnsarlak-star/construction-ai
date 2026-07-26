"""Shared normalized extraction result for CAD / IFC / GAEB / structured parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.ocr.types import DocumentExtractionResult, ExtractionPhase, OcrPageResult


@dataclass
class NormalizedExtractionResult:
    """
    Common envelope for structured native extractors (IFC, GAEB, future DXF structured).

    merged_text feeds the rule-engine corpus.
    structured + method + confidenceScore persist in Document.meta_json.
    """

    merged_text: str
    extraction_method: str
    confidence_score: float
    structured: dict[str, Any] = field(default_factory=dict)
    needs_manual_review: bool = False
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        phase = (
            ExtractionPhase.FAILED.value
            if self.error and self.needs_manual_review and not self._has_corpus_text()
            else ExtractionPhase.COMPLETED.value
        )
        return {
            "extraction": {
                "phase": phase,
                "method": self.extraction_method,
                "confidenceScore": round(float(self.confidence_score), 2),
                "structured": self.structured,
                "needsManualReview": self.needs_manual_review,
                "provider": self.extraction_method,
                "error": self.error,
                "notes": self.notes,
                "progressPercent": 100 if phase == ExtractionPhase.COMPLETED.value else 0,
                "pageCount": 1,
                "ocrPageCount": 0,
                "failedPages": [] if not self.needs_manual_review else [1],
                "pdfKind": "n/a",
            }
        }

    def _has_corpus_text(self) -> bool:
        t = (self.merged_text or "").strip()
        return bool(t) and not t.startswith(
            ("[EXTRACT_ERROR]", "[IFC_EMPTY]", "[GAEB_EMPTY]", "[IFC_ERROR]", "[GAEB_ERROR]")
        )

    def to_document_result(self) -> DocumentExtractionResult:
        ok = self._has_corpus_text()
        page = OcrPageResult(
            page=1,
            text=self.merged_text if ok else (self.merged_text or ""),
            confidence=float(self.confidence_score) if ok else 0.0,
            needs_manual_review=self.needs_manual_review or not ok,
            source="native",
            kind="searchable" if ok else "empty",
            error=self.error,
            contains_drawing=self.extraction_method.startswith(("ifc", "dxf", "dwg", "rvt")),
        )
        return DocumentExtractionResult(
            pages=[page],
            merged_text=self.merged_text or "",
            pdf_kind="n/a",
            page_count=1,
            ocr_page_count=0,
            failed_pages=[] if ok else [1],
            needs_manual_review=self.needs_manual_review or not ok,
            provider=self.extraction_method,
            phase=(
                ExtractionPhase.COMPLETED.value
                if ok or (self.merged_text and not (self.error and not ok))
                else ExtractionPhase.FAILED.value
            ),
            error=self.error,
            extraction_method=self.extraction_method,
            confidence_score=self.confidence_score,
            structured=self.structured,
            notes=list(self.notes),
        )
