"""Canonical Document Model (CDM) writer — Phase 1.

Additive only: produces meta_json.canonical without changing extracted_text
or the existing extraction envelope. Gated by settings.cdm_enabled (default OFF).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

CDM_PARSER_VERSION = "cdm-1.0.0"

_REF_PATTERNS = [
    re.compile(r"\b(?:dwg|drawing|plan|sheet|plan)\s*[:\-]?\s*([A-Z]{0,3}-?\d{1,4}[A-Z]?)\b", re.I),
    re.compile(r"\b(?:pos|oz|item)\s*[:\-]?\s*([\d.]+)\b", re.I),
    re.compile(r"\b(?:DIN|EN|ISO|VOB|NBR|ASTM)\s*[\w.\-/]+\b", re.I),
]


def build_canonical_document(
    *,
    document_id: int | None,
    project_id: int | None,
    category: str,
    original_name: str,
    content_type: str | None,
    extracted_text: str,
    extraction: dict[str, Any] | None,
    pages: list[dict[str, Any]] | None = None,
    source_filename: str | None = None,
) -> dict[str, Any]:
    """
    Build Part 1 CanonicalDocument dict from extraction outputs.

    Never mutates extracted_text; callers persist under meta_json.canonical.
    """
    extraction = extraction or {}
    method = str(extraction.get("method") or extraction.get("provider") or "unknown")
    confidence = _as_float(extraction.get("confidenceScore"), default=_default_confidence(method))
    structured = extraction.get("structured") if isinstance(extraction.get("structured"), dict) else {}
    needs_review = bool(extraction.get("needsManualReview"))
    filename = source_filename or original_name or "document"
    suffix = _suffix(filename)
    subtype = _infer_subtype(category=category, method=method, suffix=suffix, structured=structured)

    content_units = _content_units_from_pages(pages, confidence) or _content_units_from_text(
        extracted_text, confidence, method=method
    )
    tables = _tables_from_structured(structured, method=method, confidence=confidence)
    if not tables:
        tables = _tables_from_excelish_text(extracted_text, confidence)

    spatial = _spatial_from_structured(structured, method=method)
    quantities = _quantities_from_structured(structured, method=method)
    identity = _identity_from_structured(
        structured, method=method, filename=filename, extracted_text=extracted_text
    )
    langs = _detect_languages(extracted_text)
    links_out = _collect_links(content_units, extracted_text)
    content_hash = hashlib.sha256((extracted_text or "").encode("utf-8", errors="ignore")).hexdigest()

    return {
        "document_id": document_id,
        "project_id": project_id,
        "category": category,
        "subtype": subtype,
        "language_primary": langs[0] if langs else None,
        "languages_detected": langs,
        "extraction": {
            "method": method,
            "confidence_score": confidence,
            "needs_manual_review": needs_review,
            "source_formats": _source_formats(content_type, suffix, method),
        },
        "identity": identity,
        "content_units": content_units,
        "tables": tables,
        "spatial": spatial,
        "quantities_summary": quantities,
        "links_out": links_out,
        "provenance": {
            "parser_version": CDM_PARSER_VERSION,
            "normalized_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": content_hash,
        },
    }


def build_canonical_from_meta_json(
    *,
    document_id: int | None,
    project_id: int | None,
    category: str,
    original_name: str,
    content_type: str | None,
    extracted_text: str,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = meta or {}
    extraction = meta.get("extraction") if isinstance(meta.get("extraction"), dict) else {}
    pages = meta.get("pages") if isinstance(meta.get("pages"), list) else None
    return build_canonical_document(
        document_id=document_id,
        project_id=project_id,
        category=category,
        original_name=original_name,
        content_type=content_type,
        extracted_text=extracted_text,
        extraction=extraction,
        pages=pages,
        source_filename=original_name,
    )


# ----- helpers -----


def _suffix(name: str) -> str:
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _as_float(value: Any, *, default: float) -> float:
    try:
        if value is None:
            return default
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def _default_confidence(method: str) -> float:
    m = (method or "").lower()
    if m in {"ifc_native", "gaeb_native", "gaeb90_fixed"}:
        return 94.0
    if m == "dxf_native":
        return 78.0
    if m in {"dwg_harvest", "rvt_harvest"}:
        return 50.0
    if "vision" in m:
        return 45.0
    if "ocr" in m:
        return 35.0
    return 70.0


def _infer_subtype(*, category: str, method: str, suffix: str, structured: dict[str, Any]) -> str:
    m = (method or "").lower()
    if m == "ifc_native" or suffix == ".ifc":
        return "ifc_model"
    if m == "gaeb_native" or m == "gaeb90_fixed" or suffix.startswith(".x8") or suffix.startswith(".d8"):
        return "gaeb_lv"
    if m == "dxf_native" or suffix == ".dxf":
        return "cad_dxf"
    if m == "dwg_harvest" or suffix == ".dwg":
        return "cad_dwg"
    if m.startswith("rvt") or suffix in {".rvt", ".rfa", ".rte", ".rft"}:
        return "cad_revit"
    if category == "drawing":
        return "drawing_sheet"
    if category == "schedule":
        return "baseline_programme"
    if category == "standard":
        return "uploaded_standard_pdf" if suffix == ".pdf" else "uploaded_standard"
    if structured.get("format_family") == "gaeb":
        return "gaeb_lv"
    # tender pack — coarse subtype until classifier lands
    if suffix in {".xlsx", ".xls", ".csv"}:
        return "excel_boq_candidate"
    if suffix in {".docx", ".doc"}:
        return "tender_prose"
    return "tender_document"


def _source_formats(content_type: str | None, suffix: str, method: str) -> list[str]:
    out: list[str] = []
    if content_type:
        out.append(content_type)
    if suffix:
        out.append(suffix.lstrip("."))
    if method and method not in out:
        out.append(method)
    return out


def _detect_languages(text: str) -> list[str]:
    sample = (text or "")[:8000]
    if not sample.strip():
        return []
    fa = len(re.findall(r"[\u0600-\u06FF]", sample))
    de_markers = len(re.findall(r"\b(?:und|der|die|das|mit|für|Bau|Leistung)\b", sample, re.I))
    en_markers = len(re.findall(r"\b(?:the|and|of|contract|drawing|shall)\b", sample, re.I))
    scores = {"fa": fa, "de": de_markers * 8, "en": en_markers * 6}
    ranked = [lang for lang, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True) if score > 0]
    return ranked[:3]


def _new_unit_id(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


def _extract_refs(text: str) -> list[str]:
    refs: list[str] = []
    for pat in _REF_PATTERNS:
        for m in pat.finditer(text or ""):
            refs.append(m.group(0).strip())
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        key = r.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:20]


def _content_units_from_pages(
    pages: list[dict[str, Any]] | None, confidence: float
) -> list[dict[str, Any]]:
    if not pages:
        return []
    units: list[dict[str, Any]] = []
    order = 0
    for page in pages:
        page_no = page.get("page") or page.get("page_number")
        text = (page.get("text") or "").strip()
        if not text:
            continue
        page_conf = _as_float(page.get("confidence"), default=confidence)
        # Prefer paragraph splits; keep page as one unit if short
        chunks = [c.strip() for c in re.split(r"\n\s*\n+", text) if c.strip()]
        if len(chunks) <= 1:
            chunks = [text]
        for chunk in chunks[:200]:
            order += 1
            unit_type = "heading" if len(chunk) < 80 and chunk.isupper() else "paragraph"
            if re.match(r"^\s*(?:article|clause|section|§)\b", chunk, re.I):
                unit_type = "clause_candidate"
            units.append(
                {
                    "id": _new_unit_id("cu", order),
                    "unit_type": unit_type,
                    "text": chunk[:4000],
                    "language": (_detect_languages(chunk) or [None])[0],
                    "page_or_sheet": page_no,
                    "bbox": None,
                    "reading_order": order,
                    "confidence": page_conf,
                    "raw_refs": _extract_refs(chunk),
                }
            )
    return units


def _content_units_from_text(text: str, confidence: float, *, method: str) -> list[dict[str, Any]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    # CAD harvests: treat non-empty lines as labels
    if method in {"dxf_native", "dwg_harvest", "rvt_harvest"}:
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip() and not ln.strip().startswith("---")]
        units = []
        for i, line in enumerate(lines[:400], start=1):
            units.append(
                {
                    "id": _new_unit_id("cu", i),
                    "unit_type": "label" if len(line) < 120 else "note",
                    "text": line[:2000],
                    "language": (_detect_languages(line) or [None])[0],
                    "page_or_sheet": None,
                    "bbox": None,
                    "reading_order": i,
                    "confidence": confidence,
                    "raw_refs": _extract_refs(line),
                }
            )
        return units

    paras = [p.strip() for p in re.split(r"\n\s*\n+", cleaned) if p.strip()]
    if len(paras) <= 1:
        # line-based fallback
        paras = [ln.strip() for ln in cleaned.splitlines() if ln.strip()][:300]
    units = []
    for i, para in enumerate(paras[:400], start=1):
        unit_type = "paragraph"
        if re.match(r"^\s*(?:article|clause|section|§|materie|ماده)\b", para, re.I):
            unit_type = "clause_candidate"
        elif len(para) < 80:
            unit_type = "note"
        units.append(
            {
                "id": _new_unit_id("cu", i),
                "unit_type": unit_type,
                "text": para[:4000],
                "language": (_detect_languages(para) or [None])[0],
                "page_or_sheet": None,
                "bbox": None,
                "reading_order": i,
                "confidence": confidence,
                "raw_refs": _extract_refs(para),
            }
        )
    return units


def _tables_from_structured(structured: dict[str, Any], *, method: str, confidence: float) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    items = structured.get("items")
    if isinstance(items, list) and items and (method == "gaeb_native" or structured.get("format_family") == "gaeb"):
        headers = ["code", "description", "qty", "unit", "unit_price", "total_price"]
        rows: list[list[str]] = []
        for it in items[:2000]:
            if not isinstance(it, dict):
                continue
            rows.append(
                [
                    str(it.get("code") or ""),
                    str(it.get("description") or ""),
                    str(it.get("qty") or ""),
                    str(it.get("unit") or ""),
                    str(it.get("unit_price") or ""),
                    str(it.get("total_price") or ""),
                ]
            )
        tables.append(
            {
                "id": "tbl-gaeb-001",
                "name": "GAEB BoQ items",
                "headers": headers,
                "rows": rows,
                "role_hint": "boq_like",
                "confidence": confidence,
            }
        )
    return tables


def _tables_from_excelish_text(text: str, confidence: float) -> list[dict[str, Any]]:
    """Best-effort table from 'a | b | c' lines (Excel extractor style)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if " | " in ln]
    if len(lines) < 2:
        return []
    rows = [ [c.strip() for c in ln.split(" | ")] for ln in lines[:500] ]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    headers = [f"col_{i+1}" for i in range(width)]
    return [
        {
            "id": "tbl-text-001",
            "name": "delimited_rows",
            "headers": headers,
            "rows": rows,
            "role_hint": "unknown",
            "confidence": min(confidence, 65.0),
        }
    ]


def _spatial_from_structured(structured: dict[str, Any], *, method: str) -> dict[str, Any] | None:
    hierarchy = structured.get("spatial_hierarchy")
    counts = structured.get("elements_by_discipline")
    if not hierarchy and not counts:
        if method == "dxf_native" and structured.get("layers"):
            return {
                "nodes": [
                    {"type": "Layer", "name": str(layer), "external_id": str(layer), "parent_id": None}
                    for layer in (structured.get("layers") or [])[:200]
                ],
                "element_counts": {},
            }
        return None
    nodes: list[dict[str, Any]] = []
    if isinstance(hierarchy, list):
        for i, node in enumerate(hierarchy[:500]):
            if isinstance(node, dict):
                nodes.append(
                    {
                        "type": node.get("type") or node.get("ifc_type") or "Spatial",
                        "name": node.get("name") or node.get("Name"),
                        "external_id": node.get("global_id") or node.get("id") or node.get("GlobalId"),
                        "parent_id": node.get("parent_id") or node.get("parent"),
                    }
                )
            else:
                nodes.append(
                    {"type": "Spatial", "name": str(node), "external_id": f"n{i}", "parent_id": None}
                )
    return {
        "nodes": nodes,
        "element_counts": counts if isinstance(counts, dict) else {},
    }


def _quantities_from_structured(structured: dict[str, Any], *, method: str) -> dict[str, Any] | None:
    if method != "gaeb_native" and structured.get("format_family") != "gaeb":
        # IFC element counts as light rollup
        if structured.get("elements_by_discipline"):
            return {
                "kind": "ifc_element_counts",
                "element_counts": structured.get("elements_by_discipline"),
                "property_highlights": structured.get("property_highlights"),
            }
        return None
    items = structured.get("items") if isinstance(structured.get("items"), list) else []
    return {
        "kind": "gaeb_boq",
        "item_count": structured.get("item_count", len(items)),
        "grand_total": structured.get("grand_total"),
        "source_version": structured.get("source_version"),
        "exchange_phase": structured.get("exchange_phase"),
        "format_family": structured.get("format_family") or "gaeb",
    }


def _identity_from_structured(
    structured: dict[str, Any],
    *,
    method: str,
    filename: str,
    extracted_text: str,
) -> dict[str, Any]:
    title = structured.get("project_name") or structured.get("name")
    if not title and isinstance(structured.get("spatial_hierarchy"), list) and structured["spatial_hierarchy"]:
        first = structured["spatial_hierarchy"][0]
        if isinstance(first, dict):
            title = first.get("name")
    if not title:
        title = PathStem(filename)

    external_ids: list[str] = []
    for key in ("project_global_id", "schema"):
        if structured.get(key):
            external_ids.append(str(structured[key]))
    for node in (structured.get("spatial_hierarchy") or [])[:5]:
        if isinstance(node, dict) and node.get("global_id"):
            external_ids.append(str(node["global_id"]))
    if structured.get("items") and isinstance(structured["items"], list):
        codes = [str(it.get("code")) for it in structured["items"][:3] if isinstance(it, dict) and it.get("code")]
        external_ids.extend(codes)

    authoring = None
    if method == "ifc_native":
        authoring = "IFC"
    elif method == "gaeb_native":
        authoring = "GAEB"
    elif method.startswith("dxf"):
        authoring = "DXF"
    elif method.startswith("dwg"):
        authoring = "DWG"
    elif method.startswith("rvt"):
        authoring = "Revit"

    # light revision sniff from text
    rev = None
    m = re.search(r"\brev(?:ision)?\s*[:\-]?\s*([A-Z0-9.]+)\b", extracted_text or "", re.I)
    if m:
        rev = m.group(1)

    return {
        "title": title,
        "revision": rev,
        "revision_date": structured.get("date") or structured.get("revision_date"),
        "authoring_system": authoring,
        "external_ids": list(dict.fromkeys(external_ids))[:30],
    }


def PathStem(filename: str) -> str:
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base:
        return base.rsplit(".", 1)[0]
    return base or "document"


def _collect_links(units: list[dict[str, Any]], text: str) -> list[str]:
    found: list[str] = []
    for u in units:
        found.extend(u.get("raw_refs") or [])
    found.extend(_extract_refs(text or ""))
    # unique
    out: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:50]


def attach_canonical_payload(meta: dict[str, Any], canonical: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied meta dict with canonical set (does not remove extraction/pages)."""
    out = dict(meta or {})
    out["canonical"] = canonical
    return out
