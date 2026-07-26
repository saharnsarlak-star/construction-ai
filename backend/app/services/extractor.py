from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pdfplumber
from docx import Document as DocxDocument
from openpyxl import load_workbook

from app.services.ocr import extract_document, ocr_runtime_status
from app.services.ocr.types import ExtractionPhase

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".dwg",
    ".dxf",
    ".rvt",
    ".rfa",
    ".rte",
    ".rft",
    ".ifc",
    ".x81",
    ".x82",
    ".x83",
    ".x84",
    ".x85",
    ".x86",
    ".d81",
    ".d82",
    ".d83",
    ".d84",
    ".d85",
    ".d86",
}

_GAEB_EXTENSIONS = {
    ".x81",
    ".x82",
    ".x83",
    ".x84",
    ".x85",
    ".x86",
    ".d81",
    ".d82",
    ".d83",
    ".d84",
    ".d85",
    ".d86",
}

_MAX_DOCX_IMAGES = 12
_MIN_NATIVE_TEXT_CHARS = 40
_MIN_PAGE_TEXT_CHARS = 20


def extract_text_from_file(
    path: Path,
    *,
    allow_ocr: bool = True,
    treat_as_drawing: bool = False,
) -> str:
    """
    Backward-compatible facade used by analyzer/upload.

    PDFs go through the modular DocumentPipeline (detect → OCR → merge).
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            result = extract_document(
                path, allow_ocr=allow_ocr, treat_as_drawing=treat_as_drawing
            )
            if result.merged_text:
                return result.merged_text
            if result.error:
                return f"[EXTRACT_ERROR] {path.name}: {result.error}"
            return f"[OCR_EMPTY] {path.name}\nNo extractable text found."
        if suffix == ".docx":
            return _extract_docx(path, allow_ocr=allow_ocr)
        if suffix in {".xlsx", ".xls"}:
            return _extract_excel(path)
        if suffix in {".txt", ".csv"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
            if not allow_ocr:
                return (
                    f"[OCR_SKIPPED] {path.name}\n"
                    "OCR skipped during bulk upload. Use re-extract if text is needed."
                )
            return _extract_image(path)
        if suffix in {".dwg", ".dxf", ".rvt", ".rfa", ".rte", ".rft"}:
            from app.services.cad_extractor import extract_cad_text

            return extract_cad_text(path)
        if suffix == ".ifc":
            from app.services.ifc_extractor import extract_ifc

            return extract_ifc(path).merged_text
        if suffix in _GAEB_EXTENSIONS:
            from app.services.gaeb_extractor import extract_gaeb

            return extract_gaeb(path).merged_text
        if suffix == ".doc":
            return (
                f"[BINARY_OR_IMAGE_FILE] {path.name}\n"
                "Text extraction for this format is limited in MVP. "
                "Convert .doc to .docx or upload a searchable PDF."
            )
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        return f"[EXTRACT_ERROR] {path.name}: {exc}"


def extract_document_full(
    path: Path,
    *,
    allow_ocr: bool = True,
    treat_as_drawing: bool = False,
    on_progress=None,
):
    """Full structured extraction (pages JSON + merged text + optional structured meta)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_document(
            path,
            allow_ocr=allow_ocr,
            treat_as_drawing=treat_as_drawing,
            on_progress=on_progress,
        )
    if suffix == ".ifc":
        from app.services.ifc_extractor import extract_ifc

        return extract_ifc(path).to_document_result()
    if suffix in _GAEB_EXTENSIONS:
        from app.services.gaeb_extractor import extract_gaeb

        return extract_gaeb(path).to_document_result()

    # Non-PDF: wrap flat extract into a minimal result-like dict via pipeline types
    from app.services.ocr.types import DocumentExtractionResult, OcrPageResult

    text = extract_text_from_file(path, allow_ocr=allow_ocr, treat_as_drawing=treat_as_drawing)
    ok = has_usable_text(text)
    method = None
    if suffix == ".dxf":
        method = "dxf_native"
    elif suffix == ".dwg":
        method = "dwg_harvest"
    elif suffix in {".rvt", ".rfa", ".rte", ".rft"}:
        method = "rvt_harvest"
    page = OcrPageResult(
        page=1,
        text=text if ok else "",
        confidence=90.0 if ok else 0.0,
        needs_manual_review=not ok,
        source="native",
        kind="searchable" if ok else "empty",
        error=None if ok else text[:200],
        contains_drawing=treat_as_drawing or suffix in {".dwg", ".dxf", ".rvt", ".rfa", ".rte", ".rft"},
    )
    return DocumentExtractionResult(
        pages=[page],
        merged_text=text if ok else text,
        pdf_kind="n/a",
        page_count=1,
        ocr_page_count=0,
        failed_pages=[] if ok else [1],
        needs_manual_review=not ok,
        provider=method or "legacy",
        phase=ExtractionPhase.COMPLETED.value if ok else ExtractionPhase.FAILED.value,
        extraction_method=method,
        confidence_score=82.0 if ok and method == "dxf_native" else (50.0 if ok and method else None),
    )


def has_usable_text(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith(
        (
            "[EXTRACT_ERROR]",
            "[BINARY_OR_IMAGE_FILE]",
            "[OCR_UNAVAILABLE]",
            "[OCR_EMPTY]",
            "[OCR_SKIPPED]",
            "[CAD_EMPTY]",
            "[CAD_UNSUPPORTED]",
            "[IFC_EMPTY]",
            "[IFC_ERROR]",
            "[GAEB_EMPTY]",
            "[GAEB_ERROR]",
        )
    ):
        return False
    cleaned = re.sub(r"^\[OCR_APPLIED\][^\n]*\n?", "", stripped, flags=re.IGNORECASE)
    cleaned = re.sub(r"^---\s*cad:[^\n]*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^---\s*ifc:[^\n]*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^---\s*gaeb:[^\n]*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\[(?:DWG|DXF|Revit|DXF-fallback) strings\]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"---\s*(page|sheet|ocr)[^-\n]*---", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[OCR_TRUNCATED\][^\n]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[NEEDS_MANUAL_REVIEW\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return len(cleaned) >= _MIN_NATIVE_TEXT_CHARS


def ocr_status() -> dict:
    """Runtime OCR capability for health/debug — always defined (safe import)."""
    try:
        return ocr_runtime_status()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)}


def _extract_image(path: Path) -> str:
    from app.services.ocr.factory import get_ocr_service

    svc = get_ocr_service()
    if svc is None:
        return (
            f"[OCR_UNAVAILABLE] {path.name}\n"
            "OCR engine not installed."
        )
    from PIL import Image

    with Image.open(path) as img:
        result = svc.recognize_image(img.copy(), page_number=1)
    if result.text.strip():
        return f"--- ocr: {path.name} ---\n{result.text.strip()}"
    return f"[OCR_EMPTY] {path.name}\nImage OCR produced no usable text."


def _extract_docx(path: Path, *, allow_ocr: bool = True) -> str:
    doc = DocxDocument(path)
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    native = "\n".join(parts).strip()
    if len(re.sub(r"\s+", "", native)) >= _MIN_NATIVE_TEXT_CHARS:
        return native

    if not allow_ocr:
        return native or (
            f"[OCR_SKIPPED] {path.name}\n"
            "DOCX had little/no text; OCR of embedded images was skipped."
        )

    image_texts = _ocr_docx_images(doc)
    combined = "\n\n".join([p for p in [native, image_texts] if p]).strip()
    if len(re.sub(r"\s+", "", combined)) >= _MIN_NATIVE_TEXT_CHARS:
        return "[OCR_APPLIED] DOCX images OCR'd.\n\n" + combined
    return combined or (
        f"[OCR_EMPTY] {path.name}\nWord file had no readable text or OCR-able images."
    )


def _ocr_docx_images(doc: DocxDocument) -> str:
    from app.services.ocr.factory import get_ocr_service
    import io
    from PIL import Image

    svc = get_ocr_service()
    if svc is None:
        return ""
    chunks: list[str] = []
    count = 0
    try:
        for rel in doc.part.rels.values():
            if count >= _MAX_DOCX_IMAGES:
                break
            rel_type = getattr(rel, "reltype", "") or ""
            if "image" not in rel_type:
                continue
            try:
                blob = rel.target_part.blob
            except Exception:  # noqa: BLE001
                continue
            count += 1
            try:
                with Image.open(io.BytesIO(blob)) as img:
                    result = svc.recognize_image(img.copy(), page_number=count)
                if len(result.text.strip()) >= _MIN_PAGE_TEXT_CHARS:
                    chunks.append(f"--- ocr image {count} ---\n{result.text.strip()}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("DOCX image OCR failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DOCX image walk failed: %s", exc)
    return "\n\n".join(chunks).strip()


def _extract_excel(path: Path) -> str:
    wb = load_workbook(path, data_only=True, read_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        parts.append(f"--- sheet: {sheet.title} ---")
        for row in sheet.iter_rows(values_only=True):
            values = [str(v).strip() for v in row if v is not None and str(v).strip()]
            if values:
                parts.append(" | ".join(values))
    return "\n".join(parts)


def merge_extraction_meta(existing_meta: str | None, extraction_meta: dict) -> str:
    base: dict = {}
    if existing_meta:
        try:
            parsed = json.loads(existing_meta)
            if isinstance(parsed, dict):
                base = parsed
        except json.JSONDecodeError:
            base = {}
    base.update(extraction_meta)
    return json.dumps(base, ensure_ascii=False)
