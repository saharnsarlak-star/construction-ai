"""Split standard documents into clause dicts — sample files or extracted PDF text.

Supports:
- Dev sample format (``---CLAUSE …---`` markers + structured fields)
- Heuristic numbered clauses (e.g. Iranian ``2-2-3-1`` at line start)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from app.standards_engine.ingestion.pdf_extract import PageText

ParseMode = Literal["auto", "sample", "numbered"]

_CLAUSE_MARKER_RE = re.compile(r"^---CLAUSE\s+(.+?)\s*---\s*$", re.MULTILINE)
_PAGE_MARKER_RE = re.compile(r"^---\s*page\s+(\d+)\s*---\s*$", re.IGNORECASE)
_HEADER_LINE_RE = re.compile(r"^([A-Z_]+):\s*(.+)$")

# e.g. 2-2-3-1 or 12-3-4-2 at line start (optional «بند» prefix)
_NUMBERED_CLAUSE_RE = re.compile(
    r"^(?:بند\s*)?(\d+(?:-\d+)+)\s*[-–—.:]?\s*(.*)$"
)
# e.g. «2-2 - ضوابط عمومی محیط کار» or «2-2- ضوابط…»
_SECTION_HEAD_RE = re.compile(
    r"^(\d+-\d+)\s*[-–—]\s*(.+)$"
)
_CHAPTER_RE = re.compile(
    r"^(?:فصل|chapter)\s+(?:\S+\s*[-–—]\s*)?(.+)$",
    re.IGNORECASE,
)
# TOC/index lines: "2-2-3-1 .......... 45"
_TOC_TRAIL_RE = re.compile(r"\.{3,}\s*\d+\s*$")
_VIRTUAL_PAGE_CHARS = 3500


def parse_standards_text(
    text: str,
    *,
    mode: ParseMode = "auto",
    section_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Return clause dicts from raw standard text."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []

    if mode == "sample" or (mode == "auto" and _CLAUSE_MARKER_RE.search(text)):
        clauses = _parse_sample_markers(text)
    else:
        clauses = _parse_numbered_clauses(text, page_for_line=_page_for_line_map(text))

    if section_prefix:
        prefix = section_prefix.strip().rstrip("-")
        clauses = [
            c
            for c in clauses
            if str(c.get("clause_number") or "").startswith(prefix)
        ]

    return clauses


def parse_standards_pages(
    pages: list[PageText],
    *,
    mode: ParseMode = "auto",
    section_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Parse clauses from page-aware extraction, attaching ``source_page``."""
    if not pages:
        return []

    merged = []
    page_for_line: dict[int, int] = {}
    line_no = 0
    for pg in pages:
        body = (pg.text or "").replace("\r\n", "\n")
        for raw_line in body.split("\n"):
            page_for_line[line_no] = pg.page
            merged.append(raw_line)
            line_no += 1
        merged.append("")
        page_for_line[line_no] = pg.page
        line_no += 1

    text = "\n".join(merged).strip()
    if mode == "sample" or (mode == "auto" and _CLAUSE_MARKER_RE.search(text)):
        clauses = _parse_sample_markers(text)
    else:
        clauses = _parse_numbered_clauses(text, page_for_line=page_for_line)

    if section_prefix:
        prefix = section_prefix.strip().rstrip("-")
        clauses = [
            c
            for c in clauses
            if str(c.get("clause_number") or "").startswith(prefix)
        ]
    return clauses


def _page_for_line_map(text: str, *, chars_per_page: int = _VIRTUAL_PAGE_CHARS) -> dict[int, int]:
    """Map line index → page number (PDF markers or virtual pages for Word)."""
    lines = text.replace("\r\n", "\n").splitlines()
    has_markers = any(_PAGE_MARKER_RE.match(line.strip()) for line in lines)

    page_for_line: dict[int, int] = {}
    if has_markers:
        current_page = 1
        for idx, raw_line in enumerate(lines):
            m = _PAGE_MARKER_RE.match(raw_line.strip())
            if m:
                current_page = int(m.group(1))
                continue
            page_for_line[idx] = current_page
        return page_for_line

    char_count = 0
    current_page = 1
    for idx, raw_line in enumerate(lines):
        page_for_line[idx] = current_page
        char_count += len(raw_line) + 1
        if char_count >= chars_per_page:
            current_page += 1
            char_count = 0
    return page_for_line


def _is_toc_stub(clause: dict[str, Any]) -> bool:
    """True when a clause looks like a table-of-contents index line, not body text."""
    title = str(clause.get("title") or "").strip()
    body = str(clause.get("raw_text") or "").strip()
    combined = f"{title}\n{body}".strip()
    if not _TOC_TRAIL_RE.search(combined):
        return False
    substantive = body or title
    substantive = _TOC_TRAIL_RE.sub("", substantive).strip()
    return len(substantive) < 40


def _clause_text_len(clause: dict[str, Any]) -> int:
    title = str(clause.get("title") or "").strip()
    body = str(clause.get("raw_text") or "").strip()
    if title and body.startswith(title):
        body = body[len(title) :].strip()
    return len(body or title)


def filter_substantive_clauses(
    clauses: list[dict[str, Any]],
    *,
    min_chars: int = 40,
) -> list[dict[str, Any]]:
    """Drop TOC stubs and clauses without enough body text for LLM extraction."""
    out: list[dict[str, Any]] = []
    for clause in clauses:
        if _is_toc_stub(clause):
            continue
        if _clause_text_len(clause) < min_chars:
            continue
        out.append(clause)
    return out


def parse_standards_file(
    path: str | Path,
    *,
    mode: ParseMode = "auto",
    section_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Read a UTF-8 standards file and parse clauses."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_standards_text(text, mode=mode, section_prefix=section_prefix)


def _parse_sample_markers(text: str) -> list[dict[str, Any]]:
    header: dict[str, str] = {}
    body_start = 0

    for line in text.splitlines():
        if _CLAUSE_MARKER_RE.match(line.strip()):
            body_start = text.find(line)
            break
        m = _HEADER_LINE_RE.match(line.strip())
        if m:
            header[m.group(1).strip()] = m.group(2).strip()

    chapter = header.get("CHAPTER")
    section = header.get("SECTION")
    body = text[body_start:] if body_start else text

    markers = list(_CLAUSE_MARKER_RE.finditer(body))
    if not markers:
        return []

    clauses: list[dict[str, Any]] = []
    for idx, match in enumerate(markers):
        block_start = match.end()
        block_end = markers[idx + 1].start() if idx + 1 < len(markers) else len(body)
        block = body[block_start:block_end].strip()
        parsed = _parse_sample_block(block, fallback_number=match.group(1).strip())
        parsed["chapter"] = chapter
        parsed["section"] = section
        clauses.append(parsed)

    return clauses


def _parse_sample_block(block: str, *, fallback_number: str) -> dict[str, Any]:
    clause_number = fallback_number
    title = ""
    raw_text = ""

    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("شماره بند:"):
            clause_number = line.split(":", 1)[1].strip() or clause_number
        elif line.startswith("عنوان:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("متن:"):
            rest = line.split(":", 1)[1].strip()
            text_lines: list[str] = []
            if rest:
                text_lines.append(rest)
            i += 1
            while i < len(lines):
                text_lines.append(lines[i].rstrip())
                i += 1
            raw_text = "\n".join(text_lines).strip()
            break
        i += 1

    return {
        "clause_number": clause_number,
        "title": title,
        "raw_text": raw_text,
    }


def _parse_numbered_clauses(
    text: str,
    *,
    page_for_line: dict[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Heuristic split for PDF-extracted standards with numeric clause ids."""
    lines = text.splitlines()
    chapter: str | None = None
    section: str | None = None
    current: dict[str, Any] | None = None
    body_lines: list[str] = []
    clauses: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current, body_lines
        if current is None:
            return
        current["raw_text"] = "\n".join(body_lines).strip()
        if current.get("title") and current["raw_text"].startswith(current["title"]):
            current["raw_text"] = current["raw_text"][len(current["title"]) :].strip()
        clauses.append(current)
        current = None
        body_lines = []

    for line_idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if _PAGE_MARKER_RE.match(line):
            continue
        if not line:
            if current is not None:
                body_lines.append("")
            continue

        ch = _CHAPTER_RE.match(line)
        if ch:
            flush()
            chapter = ch.group(1).strip()
            continue

        sec = _SECTION_HEAD_RE.match(line)
        if sec and len(sec.group(1).split("-")) == 2:
            flush()
            section = sec.group(1).strip()
            title_tail = sec.group(2).strip()
            if title_tail and not _NUMBERED_CLAUSE_RE.match(line):
                continue

        m = _NUMBERED_CLAUSE_RE.match(line)
        if m:
            flush()
            num = m.group(1).strip()
            rest = (m.group(2) or "").strip()
            source_page = page_for_line.get(line_idx) if page_for_line else None
            current = {
                "clause_number": num,
                "title": rest,
                "raw_text": "",
                "chapter": chapter,
                "section": section or _section_from_clause_number(num),
                "source_page": source_page,
            }
            if rest:
                body_lines = [rest]
            else:
                body_lines = []
            continue

        if current is not None:
            body_lines.append(raw_line.rstrip())

    flush()
    clauses = _dedupe_clauses(clauses)
    return [c for c in clauses if not _is_toc_stub(c)]


def _section_from_clause_number(clause_number: str) -> str | None:
    parts = clause_number.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return None


def _dedupe_clauses(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in clauses:
        num = str(c.get("clause_number") or "")
        if not num or num in seen:
            continue
        seen.add(num)
        out.append(c)
    return out
