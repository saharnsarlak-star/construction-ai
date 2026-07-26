"""Document extraction pipeline: detect → native/OCR → merge → structured result."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

import pdfplumber

from app.services.ocr.classifier import classify_document, classify_native_page_text
from app.services.ocr.factory import get_ocr_service
from app.services.ocr.types import (
    DocumentExtractionResult,
    ExtractionPhase,
    OcrPageResult,
    PdfPageKind,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 40
_MIN_NATIVE_CHARS = 40
_CONFIDENCE_REVIEW_THRESHOLD = 85.0

ProgressCb = Callable[[ExtractionPhase, int, int, str | None], None]


def extract_document(
    path: Path,
    *,
    allow_ocr: bool = True,
    treat_as_drawing: bool = False,
    max_pages: int = _MAX_PAGES,
    on_progress: ProgressCb | None = None,
) -> DocumentExtractionResult:
    """
    Automatically process any PDF (searchable or scanned).

    Non-PDF files fall back to lightweight extractors in extractor.py.
    """
    suffix = path.suffix.lower()
    if suffix != ".pdf":
        return DocumentExtractionResult(
            merged_text="",
            phase=ExtractionPhase.FAILED.value,
            error=f"Pipeline expects PDF, got {suffix}",
        )

    def _progress(phase: ExtractionPhase, done: int, total: int, note: str | None = None) -> None:
        if on_progress:
            on_progress(phase, done, total, note)

    try:
        _progress(ExtractionPhase.CONVERTING, 0, 1, "Opening PDF")
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            limit = min(page_count, max_pages)
            native_by_page: dict[int, str] = {}
            kinds: list[PdfPageKind] = []
            for i, page in enumerate(pdf.pages[:limit], start=1):
                text = (page.extract_text() or "").strip()
                native_by_page[i] = text
                kinds.append(classify_native_page_text(text))

        pdf_kind = classify_document(kinds)
        ocr = get_ocr_service() if allow_ocr else None
        provider_name = ocr.name if ocr else "native-only"

        pages: list[OcrPageResult] = []
        failed_pages: list[int] = []
        ocr_used = 0

        # Render via pypdfium2 only when needed
        pdfium_doc = None
        if allow_ocr and any(k != PdfPageKind.SEARCHABLE for k in kinds):
            _progress(ExtractionPhase.CONVERTING, 0, limit, "Rasterizing pages for OCR")
            try:
                import pypdfium2 as pdfium

                pdfium_doc = pdfium.PdfDocument(str(path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("pypdfium2 open failed: %s", exc)
                pdfium_doc = None

        try:
            for i in range(1, limit + 1):
                native = native_by_page.get(i, "")
                kind = kinds[i - 1]
                _progress(ExtractionPhase.EXTRACTING, i - 1, limit, f"Page {i}")

                if kind == PdfPageKind.SEARCHABLE and len(re.sub(r"\s+", "", native)) >= _MIN_NATIVE_CHARS:
                    conf = 98.0
                    page_result = OcrPageResult(
                        page=i,
                        text=native,
                        language=_guess_lang(native),
                        confidence=conf,
                        contains_tables=_looks_like_table(native),
                        contains_drawing=treat_as_drawing or _looks_like_drawing(native),
                        contains_stamp=_looks_like_stamp(native),
                        contains_signature=_looks_like_signature(native),
                        needs_manual_review=False,
                        source="native",
                        kind=kind.value,
                    )
                    pages.append(page_result)
                    continue

                # Scanned / weak text → OCR
                if not allow_ocr or ocr is None or pdfium_doc is None:
                    page_result = OcrPageResult(
                        page=i,
                        text=native,
                        language=_guess_lang(native),
                        confidence=30.0 if native else 0.0,
                        contains_drawing=treat_as_drawing,
                        needs_manual_review=True,
                        source="native" if native else "ocr",
                        kind=kind.value,
                        error=None if native else "OCR unavailable or skipped",
                    )
                    if not native:
                        failed_pages.append(i)
                    pages.append(page_result)
                    continue

                _progress(ExtractionPhase.OCR, i - 1, limit, f"OCR page {i}")
                try:
                    page = pdfium_doc[i - 1]
                    bitmap = page.render(scale=180 / 72)
                    pil = bitmap.to_pil()
                    ocr_result = ocr.recognize_image(pil, page_number=i)
                    bitmap.close()
                    page.close()
                    ocr_used += 1

                    # Hybrid: keep native fragment if OCR empty
                    if not ocr_result.text.strip() and native:
                        ocr_result.text = native
                        ocr_result.source = "hybrid"
                    if treat_as_drawing:
                        ocr_result.contains_drawing = True
                    if ocr_result.confidence < _CONFIDENCE_REVIEW_THRESHOLD:
                        ocr_result.needs_manual_review = True
                    if ocr_result.error and not ocr_result.text.strip():
                        failed_pages.append(i)
                    pages.append(ocr_result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Page %s OCR failed: %s", i, exc)
                    failed_pages.append(i)
                    pages.append(
                        OcrPageResult(
                            page=i,
                            text=native,
                            confidence=0.0,
                            contains_drawing=treat_as_drawing,
                            needs_manual_review=True,
                            source="ocr",
                            kind=kind.value,
                            error=str(exc),
                        )
                    )
        finally:
            if pdfium_doc is not None:
                pdfium_doc.close()

        _progress(ExtractionPhase.MERGING, limit, limit, "Merging pages")
        merged_parts: list[str] = []
        for p in pages:
            body = (p.text or "").strip()
            if not body:
                continue
            header = f"--- page {p.page} ({p.source}, conf={p.confidence:.0f}) ---"
            flags = []
            if p.needs_manual_review:
                flags.append("NEEDS_MANUAL_REVIEW")
            if p.contains_stamp:
                flags.append("STAMP")
            if p.contains_signature:
                flags.append("SIGNATURE")
            if p.contains_drawing:
                flags.append("DRAWING")
            if flags:
                header += " [" + ",".join(flags) + "]"
            merged_parts.append(f"{header}\n{body}")

        if page_count > limit:
            merged_parts.append(
                f"[OCR_TRUNCATED] Only first {limit} of {page_count} pages were processed."
            )

        needs_review = any(p.needs_manual_review for p in pages) or bool(failed_pages)
        result = DocumentExtractionResult(
            pages=pages,
            merged_text="\n\n".join(merged_parts).strip(),
            pdf_kind=pdf_kind,
            page_count=page_count,
            ocr_page_count=ocr_used,
            failed_pages=failed_pages,
            needs_manual_review=needs_review,
            provider=provider_name,
            phase=ExtractionPhase.COMPLETED.value,
        )
        _progress(ExtractionPhase.COMPLETED, limit, limit, None)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Document pipeline failed for %s", path)
        return DocumentExtractionResult(
            phase=ExtractionPhase.FAILED.value,
            error=str(exc),
            merged_text=f"[EXTRACT_ERROR] {path.name}: {exc}",
        )


def _guess_lang(text: str) -> str:
    if re.search(r"[\u0600-\u06FF]", text):
        return "fa"
    if re.search(r"[äöüÄÖÜß]", text):
        return "de"
    return "en"


def _looks_like_table(text: str) -> bool:
    return bool(re.search(r"(\|.+\||\t.+\t|ردیف|Qty|Einheit)", text, re.I))


def _looks_like_drawing(text: str) -> bool:
    return bool(re.search(r"(elevation|section|grid|تراز|محور|Room\s*\d|Ø|mm\b)", text, re.I))


def _looks_like_stamp(text: str) -> bool:
    return bool(re.search(r"(مهر|stamp|Siegel)", text, re.I))


def _looks_like_signature(text: str) -> bool:
    return bool(re.search(r"(امضا|signature|Unterschrift)", text, re.I))
