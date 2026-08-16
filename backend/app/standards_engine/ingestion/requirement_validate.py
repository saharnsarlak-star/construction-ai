"""Post-LLM validation and normalization for extracted standard requirements."""

from __future__ import annotations

import re
from typing import Any

from app.standards_engine.ingestion.modality_patterns import LocaleCode, infer_modality

_THICKNESS_WIDTH_FA_RE = re.compile(
    r"ضخامت\s*(\d+(?:\.\d+)?)\s*و\s*عرض\s*(\d+(?:\.\d+)?)\s*(سانتی[\u200c\s]*متر|cm|متر|m|میلی[\u200c\s]*متر|mm)?",
    re.IGNORECASE,
)
_THICKNESS_WIDTH_EN_RE = re.compile(
    r"thickness\s*(\d+(?:\.\d+)?)\s*(?:and|&)\s*width\s*(\d+(?:\.\d+)?)\s*(cm|mm|m|in|inches)?",
    re.IGNORECASE,
)
_NUMERIC_RANGE_RE = re.compile(
    r"(?:حداقل|minimum|min)\s*(\d+(?:\.\d+)?)\s*(?:و|تا|–|-)\s*(?:حداکثر|maximum|max)?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _dedupe_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("requirement_type") or ""),
            _norm_text(str(item.get("requirement_text") or ""))[:200],
            str(item.get("min_value")),
            str(item.get("max_value")),
            str(item.get("unit") or ""),
        ]
    )


def infer_requirement_type_from_text(
    text: str,
    current: str,
    *,
    locale: LocaleCode = "auto",
) -> str:
    """Correct LLM modality using locale-aware obligation markers."""
    return infer_modality(text, current, locale=locale)


def _split_thickness_width(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Split combined thickness+width into separate minimum requirements."""
    text = str(item.get("requirement_text") or "")
    m = _THICKNESS_WIDTH_FA_RE.search(text) or _THICKNESS_WIDTH_EN_RE.search(text)
    if not m:
        return [item]

    thickness, width = m.group(1), m.group(2)
    unit_raw = (m.group(3) or "cm").strip()
    unit = "cm" if "سانتی" in unit_raw or unit_raw.lower() == "cm" else unit_raw.lower()

    base = dict(item)
    out: list[dict[str, Any]] = []
    t_item = {
        **base,
        "requirement_type": "minimum",
        "requirement_text": f"minimum thickness {thickness} {unit_raw}".strip(),
        "min_value": float(thickness),
        "max_value": None,
        "unit": unit,
    }
    w_item = {
        **base,
        "requirement_type": "minimum",
        "requirement_text": f"minimum width {width} {unit_raw}".strip(),
        "min_value": float(width),
        "max_value": None,
        "unit": unit,
    }
    out.extend([t_item, w_item])
    return out


def _fix_min_max_consistency(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    mn, mx = out.get("min_value"), out.get("max_value")
    if mn is not None and mx is not None:
        try:
            fmn, fmx = float(mn), float(mx)
            if fmn > fmx:
                out["min_value"], out["max_value"] = fmx, fmn
        except (TypeError, ValueError):
            pass
    return out


def validate_requirements(
    requirements: list[dict[str, Any]],
    *,
    clause_number: str | None = None,
    locale: LocaleCode = "auto",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate and normalize LLM-extracted requirements."""
    warnings: list[dict[str, Any]] = []
    expanded: list[dict[str, Any]] = []

    for raw in requirements:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("requirement_text") or "").strip()
        if not text:
            warnings.append(
                {
                    "clause_number": clause_number,
                    "code": "empty_requirement_text",
                    "message": "Skipped requirement with empty text",
                }
            )
            continue

        item = dict(raw)
        req_type = str(item.get("requirement_type") or "mandatory").strip().lower()
        item["requirement_type"] = infer_requirement_type_from_text(text, req_type, locale=locale)

        if item["requirement_type"] != req_type:
            warnings.append(
                {
                    "clause_number": clause_number,
                    "code": "modality_corrected",
                    "message": f"Corrected requirement_type {req_type!r} → {item['requirement_type']!r}",
                    "requirement_text": text[:120],
                }
            )

        split_items = _split_thickness_width(item)
        if len(split_items) > 1:
            warnings.append(
                {
                    "clause_number": clause_number,
                    "code": "thickness_width_split",
                    "message": "Split combined thickness/width into separate requirements",
                    "requirement_text": text[:120],
                }
            )
        for si in split_items:
            fixed = _fix_min_max_consistency(si)
            if fixed.get("min_value") is not None and fixed.get("max_value") is None:
                rng = _NUMERIC_RANGE_RE.search(str(fixed.get("requirement_text") or ""))
                if rng:
                    fixed["min_value"] = float(rng.group(1))
                    fixed["max_value"] = float(rng.group(2))
                    fixed["requirement_type"] = "conditional"
            expanded.append(fixed)

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in expanded:
        key = _dedupe_key(item)
        if key in seen:
            warnings.append(
                {
                    "clause_number": clause_number,
                    "code": "duplicate_dropped",
                    "message": "Dropped duplicate requirement",
                    "requirement_text": str(item.get("requirement_text") or "")[:120],
                }
            )
            continue
        seen.add(key)
        deduped.append(item)

    return deduped, warnings
