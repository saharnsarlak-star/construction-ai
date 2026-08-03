"""GAEB 90 fixed-width (punch-card) BOQ parser.

Fallback for older German LV files (.D8x) that are not GAEB DA XML.
Lines are 80 characters; cols 1–2 = Satzart, cols 75–80 = Satznummer.
Satzart 00 contains '90' near the OZ mask / version marker (cols 72–73 = 90).

Feature flag: GAEB90_ENABLED (default OFF).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.services.normalized_extraction import NormalizedExtractionResult

logger = logging.getLogger(__name__)

_LINE_RE = re.compile(r"^.{80}$")


def looks_like_gaeb90(path: str | Path, *, sample_bytes: bytes | None = None) -> bool:
    """Sniff GAEB 90 vs DA XML without requiring the feature flag."""
    path = Path(path)
    raw = sample_bytes
    if raw is None:
        try:
            raw = path.read_bytes()[:8_000]
        except OSError:
            return False
    head = raw.lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<GAEB") or head.startswith(b"<gaeb"):
        return False
    try:
        text = raw.decode("latin-1", errors="replace")
    except Exception:  # noqa: BLE001
        return False
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    # Prefer 80-char lines; tolerate slight trailing space variance
    eighty = sum(1 for ln in lines[:30] if len(ln.rstrip()) <= 80 and len(ln) >= 74)
    if eighty < max(3, len(lines[:30]) // 2):
        return False
    first = lines[0]
    if not first.startswith("00"):
        # some files have a BOM/preamble — scan first 5
        first = next((ln for ln in lines[:5] if ln.startswith("00")), first)
    # GAEB 90 marker: "90" in cols 72-73 (1-based) → index 71:73, or anywhere near end of header
    padded = first.ljust(80)
    if padded[71:73] == "90":
        return True
    if "90" in first[60:74] and first.startswith("00"):
        return True
    # Satzarten typical of GAEB 90 body
    kinds = {ln[:2] for ln in lines[:40] if len(ln) >= 2 and ln[:2].isdigit()}
    return bool({"21", "25", "26"} & kinds) and "00" in {ln[:2] for ln in lines[:5]}


def extract_gaeb90(path: str | Path) -> NormalizedExtractionResult:
    """Parse a GAEB 90 fixed-width file into the same envelope as DA XML extraction."""
    path = Path(path)
    try:
        raw = path.read_bytes()
        text = raw.decode("cp437", errors="replace")
        if text.count("�") > len(text) // 10:
            text = raw.decode("latin-1", errors="replace")
    except OSError as exc:
        return NormalizedExtractionResult(
            merged_text=f"[GAEB90_ERROR] {path.name}\n{exc}",
            extraction_method="gaeb90_fixed",
            confidence_score=0.0,
            structured={},
            needs_manual_review=True,
            error=str(exc),
            notes=[],
        )

    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return NormalizedExtractionResult(
            merged_text=f"[GAEB90_EMPTY] {path.name}\nNo lines",
            extraction_method="gaeb90_fixed",
            confidence_score=0.0,
            structured={},
            needs_manual_review=True,
            error="empty file",
            notes=[],
        )

    header = _parse_header(lines)
    items = _parse_positions(lines)
    structured: dict[str, Any] = {
        "source_version": "GAEB90",
        "exchange_phase": header.get("exchange_phase"),
        "oz_mask": header.get("oz_mask"),
        "project_title": header.get("project_title"),
        "grand_total": None,
        "item_count": len(items),
        "items": items,
        "validation_results": [],
        "format_family": "gaeb",
        "gaeb_dialect": "gaeb90_fixed",
        "line_count": len(lines),
    }
    merged = _build_merged(path.name, structured)
    conf = 88.0 if items else 40.0
    return NormalizedExtractionResult(
        merged_text=merged,
        extraction_method="gaeb90_fixed",
        confidence_score=conf if items else 0.0,
        structured=structured,
        needs_manual_review=not bool(items),
        error=None if items else "No GAEB 90 positions (Satzart 21) found",
        notes=[f"gaeb90_lines={len(lines)}", f"items={len(items)}"],
    )


def _field(line: str, start: int, end: int) -> str:
    """1-based inclusive start/end columns (GAEB convention)."""
    padded = line.ljust(80)
    return padded[start - 1 : end].strip()


def _parse_header(lines: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ln in lines[:12]:
        if len(ln) < 2:
            continue
        kind = ln[:2]
        if kind == "00":
            padded = ln.ljust(80)
            # Phase often appears early: "00 83L ..."
            m = re.search(r"00\s*(\d{2})", ln)
            out["exchange_phase"] = m.group(1) if m else None
            out["oz_mask"] = _field(ln, 63, 71) or None
            out["gaeb90_marker"] = padded[71:73]
        elif kind == "01" and "project_title" not in out:
            out["project_title"] = ln[2:74].strip()
        elif kind == "02" and "project_title" in out:
            out["project_subtitle"] = ln[2:74].strip()
    return out


def _parse_qty(raw: str, decimals: int = 3) -> float | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    try:
        val = int(digits)
        return val / (10**decimals)
    except ValueError:
        return None


def _parse_positions(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    short_parts: list[str] = []
    long_parts: list[str] = []

    def flush() -> None:
        nonlocal current, short_parts, long_parts
        if current is None:
            return
        short = " ".join(short_parts).strip()
        long = " ".join(long_parts).strip()
        desc = short or long
        if long and short and long not in short:
            desc = f"{short} — {long}" if short else long
        current["description"] = desc[:2000]
        current["short_text"] = short
        current["long_text"] = long
        items.append(current)
        current = None
        short_parts = []
        long_parts = []

    for ln in lines:
        if len(ln) < 2:
            continue
        kind = ln[:2]
        body = ln[2:74] if len(ln) >= 74 else ln[2:]
        if kind == "21":
            flush()
            body_s = body.strip()
            oz = ""
            posart = ""
            qty_raw = ""
            unit = ""
            # Spaced Freies-GAEB-Buch style: "101 NNN 00000093000m"
            m2 = re.search(
                r"(?P<oz>\S{1,9})\s+(?P<pos>[A-Za-z]{1,3})\s+(?P<qty>\d{6,14})\s*(?P<unit>[A-Za-zÄÖÜäöüß]{1,4})",
                body_s,
            )
            if m2:
                oz = m2.group("oz").strip()
                posart = m2.group("pos")
                qty_raw = m2.group("qty")
                unit = m2.group("unit")
            else:
                # Packed fixed layout: OZ(9)+POSART(3)+MENGE(11)+UNIT(4)
                oz = body[:9].strip()
                posart = body[9:12].strip() if len(body) >= 12 else ""
                qty_raw = body[12:23] if len(body) >= 23 else ""
                unit = body[23:27].strip() if len(body) >= 27 else ""
            qty = _parse_qty(qty_raw, 3)
            current = {
                "code": oz,
                "oz": oz,
                "pos_art": posart,
                "qty": qty,
                "unit": unit or None,
                "unit_price": None,
                "total_price": None,
                "description": "",
            }
            short_parts = []
            long_parts = []
        elif kind == "23" and current is not None:
            # EP (9 with 3 decimals often) + GB
            ep_raw = body[9:18] if len(body) >= 18 else body[:15]
            gb_raw = body[18:29] if len(body) >= 29 else ""
            if not re.search(r"\d", ep_raw):
                nums = re.findall(r"\d{6,}", body)
                if nums:
                    ep_raw = nums[0]
                    gb_raw = nums[1] if len(nums) > 1 else ""
            current["unit_price"] = _parse_qty(ep_raw, 3)
            current["total_price"] = _parse_qty(gb_raw, 2) if gb_raw else None
        elif kind == "25":
            # Kurztext cols 3–72
            txt = body.strip()
            if current is None:
                # orphan text — ignore or start soft item
                continue
            if txt:
                short_parts.append(txt)
        elif kind == "26":
            txt = body.strip()
            if current is not None and txt:
                long_parts.append(txt)
        elif kind in {"11", "12", "10", "99"}:
            if kind == "99":
                flush()
            elif kind in {"11", "10"} and current is not None:
                flush()
        else:
            continue
    flush()
    return items


def _build_merged(filename: str, structured: dict[str, Any]) -> str:
    lines = [
        f"--- gaeb: {filename} (GAEB90_FIXED) ---",
        f"Source version: {structured.get('source_version')}",
        f"Exchange phase: {structured.get('exchange_phase')}",
        f"OZ mask: {structured.get('oz_mask')}",
        f"Project: {structured.get('project_title')}",
        f"Items: {structured.get('item_count', 0)}",
        "",
        "Leistungsverzeichnis / BOQ positions (GAEB 90):",
    ]
    for item in structured.get("items") or []:
        code = item.get("code") or "-"
        desc = (item.get("description") or "").replace("\n", " ").strip()
        qty = item.get("qty") if item.get("qty") is not None else ""
        unit = item.get("unit") or ""
        lines.append(f"  {code} | {desc} | qty={qty} {unit}")
        lines.append("  keywords: Leistungsverzeichnis LV GAEB Position Mengen BOQ GAEB90")
    text = "\n".join(lines).strip()
    if len(text) > 120_000:
        text = text[:120_000] + "\n[GAEB_TRUNCATED]"
    return text
