from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
from docx import Document as DocxDocument
from openpyxl import load_workbook


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
}

# Soft caps so large scanned packages do not hang the API forever.
_MAX_OCR_PAGES = 10
_MIN_NATIVE_TEXT_CHARS = 40
_MIN_PAGE_TEXT_CHARS = 25

_ocr_engine = None
_ocr_engine_tried = False


def extract_text_from_file(path: Path, *, allow_ocr: bool = True) -> str:
    """
    Extract text for analysis.

    allow_ocr=False skips slow OCR (used for bulk drawing uploads so many files
    can finish before the request times out). Users can re-extract later.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return _extract_pdf(path, allow_ocr=allow_ocr)
        if suffix == ".docx":
            return _extract_docx(path)
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
        if suffix in {".dwg", ".dxf", ".doc"}:
            return (
                f"[BINARY_OR_IMAGE_FILE] {path.name}\n"
                "Text extraction for this format is limited in MVP. "
                "File is registered for checklist coverage analysis."
            )
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        return f"[EXTRACT_ERROR] {path.name}: {exc}"


def has_usable_text(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith(
        ("[EXTRACT_ERROR]", "[BINARY_OR_IMAGE_FILE]", "[OCR_UNAVAILABLE]", "[OCR_EMPTY]", "[OCR_SKIPPED]")
    ):
        return False
    cleaned = re.sub(r"---\s*(page|sheet|ocr)[^-\n]*---", "", stripped, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return len(cleaned) >= _MIN_NATIVE_TEXT_CHARS


def _extract_pdf(path: Path, *, allow_ocr: bool = True) -> str:
    native_chunks: list[str] = []
    page_count = 0
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                native_chunks.append(f"--- page {i} ---\n{text}")

    native = "\n\n".join(native_chunks).strip()
    if len(re.sub(r"\s+", "", native)) >= _MIN_NATIVE_TEXT_CHARS:
        return native

    if not allow_ocr:
        if native:
            return native
        return (
            f"[OCR_SKIPPED] {path.name}\n"
            "No native PDF text; OCR skipped during bulk/drawing upload. "
            "Use re-extract if OCR text is needed."
        )

    ocr = _ocr_pdf_pages(path, page_count=page_count or _MAX_OCR_PAGES).strip()
    if ocr.startswith(("[OCR_UNAVAILABLE]", "[EXTRACT_ERROR]")):
        return ocr
    if ocr and not ocr.startswith("[OCR_EMPTY]"):
        header = "[OCR_APPLIED] Native PDF text was empty or too short; OCR used.\n\n"
        return header + ocr
    if native:
        return native
    return (
        f"[OCR_EMPTY] {path.name}\n"
        "No extractable text found (likely a scanned/image PDF). "
        "Install OCR dependencies or upload a text-based PDF/Word file."
    )


def _extract_image(path: Path) -> str:
    text = _ocr_image_path(path)
    if text.strip():
        return f"--- ocr: {path.name} ---\n{text.strip()}"
    return (
        f"[OCR_EMPTY] {path.name}\n"
        "Image OCR produced no usable text."
    )


def _get_ocr_engine():
    """Lazy-load RapidOCR once. Returns None if package/models unavailable."""
    global _ocr_engine, _ocr_engine_tried
    if _ocr_engine_tried:
        return _ocr_engine
    _ocr_engine_tried = True
    try:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    except Exception:  # noqa: BLE001
        _ocr_engine = None
    return _ocr_engine


def _ocr_image_path(path: Path) -> str:
    engine = _get_ocr_engine()
    if engine is None:
        return (
            f"[OCR_UNAVAILABLE] {path.name}\n"
            "OCR engine not installed. Run: pip install rapidocr-onnxruntime pypdfium2 pillow"
        )
    try:
        result, _ = engine(str(path))
    except Exception as exc:  # noqa: BLE001
        return f"[EXTRACT_ERROR] OCR failed for {path.name}: {exc}"
    if not result:
        return ""
    lines = [row[1] for row in result if len(row) > 1 and row[1]]
    return "\n".join(lines)


def _ocr_pil_image(image) -> str:
    engine = _get_ocr_engine()
    if engine is None:
        return ""
    try:
        import numpy as np

        arr = np.array(image.convert("RGB"))
        result, _ = engine(arr)
    except Exception:  # noqa: BLE001
        return ""
    if not result:
        return ""
    return "\n".join(row[1] for row in result if len(row) > 1 and row[1])


def _ocr_pdf_pages(path: Path, page_count: int) -> str:
    engine = _get_ocr_engine()
    if engine is None:
        return (
            f"[OCR_UNAVAILABLE] {path.name}\n"
            "Scanned PDF detected but OCR engine is not installed. "
            "Run: pip install rapidocr-onnxruntime pypdfium2 pillow"
        )

    try:
        import pypdfium2 as pdfium
    except Exception as exc:  # noqa: BLE001
        return f"[OCR_UNAVAILABLE] pypdfium2 missing: {exc}"

    chunks: list[str] = []
    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        return f"[EXTRACT_ERROR] Cannot open PDF for OCR: {exc}"

    limit = min(len(pdf), max(page_count, 1), _MAX_OCR_PAGES)
    try:
        for i in range(limit):
            page = pdf[i]
            # ~150 DPI keeps OCR usable without huge memory use
            bitmap = page.render(scale=150 / 72)
            pil_image = bitmap.to_pil()
            text = _ocr_pil_image(pil_image).strip()
            if len(text) >= _MIN_PAGE_TEXT_CHARS:
                chunks.append(f"--- page {i + 1} (ocr) ---\n{text}")
            bitmap.close()
            page.close()
    finally:
        pdf.close()

    note = ""
    if page_count > _MAX_OCR_PAGES:
        note = f"\n\n[OCR_TRUNCATED] Only first {_MAX_OCR_PAGES} of {page_count} pages were OCR'd."
    return ("\n\n".join(chunks) + note).strip()


def _extract_docx(path: Path) -> str:
    doc = DocxDocument(path)
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


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
