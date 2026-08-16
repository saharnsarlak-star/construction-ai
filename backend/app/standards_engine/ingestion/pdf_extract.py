"""Page-aware PDF/text extraction for Standards Engine ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.extractor import extract_document_full

_PAGE_MARKER_RE = re.compile(r"^---\s*page\s+(\d+)\s*---\s*$", re.IGNORECASE | re.MULTILINE)

# Standards ingest may span full volumes — higher cap than analyze-time catalog cache.
_DEFAULT_MAX_PAGES = 200


@dataclass
class PageText:
    page: int
    text: str


@dataclass
class StandardsExtractResult:
    pages: list[PageText] = field(default_factory=list)
    merged_text: str = ""
    page_count: int = 0
    source_path: str | None = None


def _pages_from_merged_text(merged: str) -> list[PageText]:
    """Recover page boundaries from ``extract_document_full`` merged markers."""
    if not merged.strip():
        return []

    markers = list(_PAGE_MARKER_RE.finditer(merged))
    if not markers:
        return [PageText(page=1, text=merged.strip())]

    pages: list[PageText] = []
    for idx, match in enumerate(markers):
        page_num = int(match.group(1))
        start = match.end()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(merged)
        body = merged[start:end].strip()
        pages.append(PageText(page=page_num, text=body))
    return pages


def build_merged_text_from_pages(pages: list[PageText]) -> str:
    """Rebuild merged text with stable page markers for clause parsing."""
    parts: list[str] = []
    for pg in pages:
        if not (pg.text or "").strip():
            continue
        parts.append(f"--- page {pg.page} ---")
        parts.append(pg.text.strip())
    return "\n\n".join(parts).strip()


def extract_catalog_standard_pages(
    path: Path,
    *,
    max_pages: int = _DEFAULT_MAX_PAGES,
    allow_ocr: bool = False,
) -> StandardsExtractResult:
    """Extract per-page text from a catalog standard PDF (or other supported format)."""
    path = Path(path)
    result = extract_document_full(
        path,
        allow_ocr=allow_ocr,
        treat_as_drawing=False,
        max_pages=max_pages,
    )
    pages = _pages_from_merged_text(result.merged_text or "")
    if not pages and (result.merged_text or "").strip():
        pages = [PageText(page=1, text=(result.merged_text or "").strip())]

    return StandardsExtractResult(
        pages=pages,
        merged_text=build_merged_text_from_pages(pages) if pages else (result.merged_text or "").strip(),
        page_count=len(pages),
        source_path=str(path),
    )


def parse_pages_from_cached_text(cached_text: str) -> list[PageText]:
    """Parse page list from cached ``catalog_standard_assets.extracted_text``."""
    merged = (cached_text or "").replace("\r\n", "\n").strip()
    if not merged:
        return []
    return _pages_from_merged_text(merged)
