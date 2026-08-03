"""GAEB DA XML BOQ extraction via pyGAEB (core parser, no LLM extra)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.normalized_extraction import NormalizedExtractionResult

logger = logging.getLogger(__name__)

GAEB_MAX_ITEMS_IN_TEXT = 2_000
GAEB_MAX_MERGED_CHARS = 120_000

GAEB_EXTENSIONS = {
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


def extract_gaeb(path: str | Path) -> NormalizedExtractionResult:
    """Parse a GAEB DA XML (or GAEB 90 fixed-width when enabled) file into BOQ items."""
    path = Path(path)

    # Phase 8: GAEB 90 fixed-width fallback (default OFF)
    from app.config import settings
    from app.services.gaeb90_parser import extract_gaeb90, looks_like_gaeb90

    is_gaeb90 = looks_like_gaeb90(path)
    if is_gaeb90:
        if settings.gaeb90_enabled:
            return extract_gaeb90(path)
        return NormalizedExtractionResult(
            merged_text=(
                f"[GAEB90_DISABLED] {path.name}\n"
                "File looks like GAEB 90 fixed-width. Set GAEB90_ENABLED=true to parse."
            ),
            extraction_method="gaeb90_fixed",
            confidence_score=0.0,
            structured={"format_family": "gaeb", "gaeb_dialect": "gaeb90_fixed", "disabled": True},
            needs_manual_review=True,
            error="GAEB90_ENABLED is false",
            notes=["sniffed=gaeb90"],
        )

    try:
        from pygaeb import GAEBParser
    except ImportError as exc:
        return NormalizedExtractionResult(
            merged_text=f"[GAEB_ERROR] {path.name}\npyGAEB not installed: {exc}",
            extraction_method="gaeb_native",
            confidence_score=0.0,
            structured={},
            needs_manual_review=True,
            error=str(exc),
            notes=["Install pyGAEB (core, without [llm]) to enable GAEB extraction"],
        )

    try:
        # Default validation is lenient — collect issues, do not raise on WARNINGs.
        doc = GAEBParser.parse(str(path))
    except Exception as exc:  # noqa: BLE001
        logger.exception("GAEB parse failed: %s", path.name)
        # Last-chance: if sniff was wrong but content is fixed-width, try GAEB90 when enabled
        if settings.gaeb90_enabled and looks_like_gaeb90(path):
            return extract_gaeb90(path)
        return NormalizedExtractionResult(
            merged_text=f"[GAEB_ERROR] {path.name}\nFailed to parse GAEB: {exc}",
            extraction_method="gaeb_native",
            confidence_score=0.0,
            structured={},
            needs_manual_review=True,
            error=str(exc),
            notes=[],
        )

    try:
        items = _collect_items(doc)
        validation = _collect_validation(doc)
        source_version = _enum_str(getattr(doc, "source_version", None))
        exchange_phase = _enum_str(getattr(doc, "exchange_phase", None))
        grand_total = getattr(doc, "grand_total", None)

        structured: dict[str, Any] = {
            "source_version": source_version,
            "exchange_phase": exchange_phase,
            "grand_total": str(grand_total) if grand_total is not None else None,
            "item_count": len(items),
            "items": items,
            "validation_results": validation,
            "format_family": "gaeb",
        }

        has_errors = any(
            str(v.get("severity", "")).upper() in {"ERROR", "CRITICAL"} for v in validation
        )
        merged = _build_merged_text(path.name, structured)
        confidence = 96.0 if items else 90.0
        if has_errors:
            confidence = min(confidence, 91.0)

        if not items:
            return NormalizedExtractionResult(
                merged_text=merged
                if merged.startswith("[GAEB")
                else f"[GAEB_EMPTY] {path.name}\nNo BOQ items found.\n{merged}",
                extraction_method="gaeb_native",
                confidence_score=0.0 if not items else confidence,
                structured=structured,
                needs_manual_review=True,
                error="No GAEB items extracted",
                notes=[f"validation_issues={len(validation)}"],
            )

        return NormalizedExtractionResult(
            merged_text=merged,
            extraction_method="gaeb_native",
            confidence_score=confidence,
            structured=structured,
            needs_manual_review=has_errors,
            error=None,
            notes=[f"validation_issues={len(validation)}"] if validation else [],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("GAEB normalize failed: %s", path.name)
        return NormalizedExtractionResult(
            merged_text=f"[GAEB_ERROR] {path.name}\n{exc}",
            extraction_method="gaeb_native",
            confidence_score=0.0,
            structured={},
            needs_manual_review=True,
            error=str(exc),
            notes=[],
        )


def _enum_str(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    if hasattr(value, "name"):
        return str(value.name)
    return str(value)


def _collect_items(doc: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        iterable = doc.iter_items()
    except Exception:  # noqa: BLE001
        # Fallback for older shapes
        try:
            iterable = doc.award.boq.iter_items()
        except Exception:  # noqa: BLE001
            return items

    for item in iterable:
        oz = getattr(item, "oz", None)
        if not oz:
            oz = getattr(item, "full_oz", None)
            if callable(oz):
                try:
                    oz = oz()
                except Exception:  # noqa: BLE001
                    oz = None
        if not oz:
            oz_path = getattr(item, "oz_path", None) or []
            if oz_path:
                oz = ".".join(str(p) for p in oz_path)
        short_text = getattr(item, "short_text", None) or ""
        if not short_text:
            plain = getattr(item, "long_text_plain", None)
            short_text = plain or ""
        qty = getattr(item, "qty", None)
        unit = getattr(item, "unit", None)
        unit_price = getattr(item, "unit_price", None)
        total_price = getattr(item, "total_price", None)
        code = str(oz).strip() if oz is not None else ""
        items.append(
            {
                "code": code or None,
                "description": str(short_text) if short_text is not None else "",
                "qty": str(qty) if qty is not None else None,
                "unit": str(unit) if unit is not None else None,
                "unit_price": str(unit_price) if unit_price is not None else None,
                "total_price": str(total_price) if total_price is not None else None,
            }
        )
    return items


def _collect_validation(doc: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    results = getattr(doc, "validation_results", None) or []
    for issue in results:
        severity = getattr(issue, "severity", None)
        message = getattr(issue, "message", None) or str(issue)
        out.append(
            {
                "severity": _enum_str(severity) or str(severity),
                "message": str(message),
            }
        )
    return out


def _build_merged_text(filename: str, structured: dict[str, Any]) -> str:
    lines: list[str] = [
        f"--- gaeb: {filename} (GAEB_NATIVE) ---",
        f"Source version: {structured.get('source_version')}",
        f"Exchange phase: {structured.get('exchange_phase')}",
        f"Grand total: {structured.get('grand_total')}",
        f"Items: {structured.get('item_count', 0)}",
        "",
        "Leistungsverzeichnis / BOQ positions:",
    ]
    for item in (structured.get("items") or [])[:GAEB_MAX_ITEMS_IN_TEXT]:
        code = item.get("code") or "-"
        desc = (item.get("description") or "").replace("\n", " ").strip()
        qty = item.get("qty") or ""
        unit = item.get("unit") or ""
        lines.append(f"  {code} | {desc} | qty={qty} {unit}")
        # Help DE topic/keyword rules
        lines.append("  keywords: Leistungsverzeichnis LV GAEB Position Mengen BOQ")

    validation = structured.get("validation_results") or []
    if validation:
        lines.append("")
        lines.append("Validation issues:")
        for v in validation[:40]:
            lines.append(f"  [{v.get('severity')}] {v.get('message')}")

    text = "\n".join(lines).strip()
    if len(text) > GAEB_MAX_MERGED_CHARS:
        text = text[:GAEB_MAX_MERGED_CHARS] + "\n[GAEB_TRUNCATED]"
    return text
