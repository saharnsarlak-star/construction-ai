"""Map standard clauses (Code55-style) to IR tender taxonomy codes."""

from __future__ import annotations

import re
from typing import Any

from app.tender_taxonomy.catalog import _flat_index, get_entry, search_taxonomy

_TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2}


def _score_entry(query_tokens: set[str], entry) -> float:
    labels = " ".join([entry.title_fa, entry.title_en, entry.path_fa, entry.code])
    label_tokens = _tokens(labels)
    if not query_tokens or not label_tokens:
        return 0.0
    overlap = len(query_tokens & label_tokens)
    if overlap == 0:
        return 0.0
    # Prefer leaf topics for detailed clauses; subcategories for section headers.
    kind_bonus = {"topic": 1.15, "subcategory": 1.05, "category": 0.95}.get(entry.kind, 1.0)
    return (overlap / max(len(query_tokens), 1)) * kind_bonus


def _clause_body(clause: dict[str, Any]) -> str:
    return str(clause.get("raw_text") or clause.get("text") or "")


def clause_query_text(clause: dict[str, Any], *, max_chars: int = 600) -> str:
    parts = [
        str(clause.get("section_title") or ""),
        str(clause.get("title") or ""),
        str(clause.get("clause_number") or ""),
        _clause_body(clause)[:max_chars],
    ]
    return " ".join(p for p in parts if p).strip()


def map_clause_to_taxonomy(
    clause: dict[str, Any],
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    """Return best taxonomy mapping for one parsed clause."""
    query = clause_query_text(clause)
    if not query:
        return {
            "taxonomy_code": None,
            "confidence": 0.0,
            "title_fa": None,
            "kind": None,
            "candidates": [],
        }

    query_tokens = _tokens(query)
    ranked: list[tuple[float, dict[str, Any]]] = []

    # Keyword search boost
    for hit in search_taxonomy(query, limit=8):
        entry = get_entry(hit["code"])
        if entry is None:
            continue
        base = _score_entry(query_tokens, entry)
        ranked.append((base + 0.25, entry.to_dict()))

    # Full flat scan for token overlap (catches Persian stems search misses)
    for entry in _flat_index().values():
        score = _score_entry(query_tokens, entry)
        if score >= 0.08:
            ranked.append((score, entry.to_dict()))

    # Dedupe by code, keep best score
    best_by_code: dict[str, tuple[float, dict[str, Any]]] = {}
    for score, row in ranked:
        code = row["code"]
        if code not in best_by_code or score > best_by_code[code][0]:
            best_by_code[code] = (score, row)

    ordered = sorted(best_by_code.values(), key=lambda x: -x[0])[:top_k]
    if not ordered:
        return {
            "taxonomy_code": None,
            "confidence": 0.0,
            "title_fa": None,
            "kind": None,
            "candidates": [],
        }

    top_score, top = ordered[0]
    confidence = min(0.99, round(top_score, 3))
    return {
        "taxonomy_code": top["code"],
        "confidence": confidence,
        "title_fa": top["title_fa"],
        "title_en": top["title_en"],
        "kind": top["kind"],
        "path_fa": top.get("path_fa"),
        "legacy_category": top.get("legacy_category"),
        "candidates": [
            {
                "code": row["code"],
                "title_fa": row["title_fa"],
                "score": round(score, 3),
                "kind": row["kind"],
            }
            for score, row in ordered
        ],
    }


def map_clauses_to_taxonomy(
    clauses: list[dict[str, Any]],
    *,
    family_code: str | None = None,
) -> list[dict[str, Any]]:
    from app.tender_taxonomy.standard_codes import clause_slot_code

    out: list[dict[str, Any]] = []
    for clause in clauses:
        mapping = map_clause_to_taxonomy(clause)
        clause_number = str(clause.get("clause_number") or "").strip()
        tax_code = mapping.get("taxonomy_code")
        slot = (
            clause_slot_code(family_code or "IR-STD-UNKNOWN", tax_code, clause_number)
            if family_code and tax_code and clause_number
            else None
        )
        out.append(
            {
                "clause_number": clause_number,
                "section": clause.get("section"),
                "chapter": clause.get("chapter"),
                "section_title": clause.get("section_title"),
                "title": clause.get("title"),
                "source_page": clause.get("source_page"),
                "text_preview": _clause_body(clause)[:240],
                "slot_code": slot,
                **mapping,
            }
        )
    return out


def summarize_mappings(mapped: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(mapped)
    with_code = [m for m in mapped if m.get("taxonomy_code")]
    high = [m for m in with_code if (m.get("confidence") or 0) >= 0.35]
    medium = [m for m in with_code if 0.15 <= (m.get("confidence") or 0) < 0.35]
    low = [m for m in with_code if (m.get("confidence") or 0) < 0.15]
    unmapped = [m for m in mapped if not m.get("taxonomy_code")]

    by_code: dict[str, int] = {}
    for m in with_code:
        code = str(m["taxonomy_code"])
        by_code[code] = by_code.get(code, 0) + 1

    top_buckets = sorted(by_code.items(), key=lambda x: -x[1])[:15]
    return {
        "total_clauses": total,
        "mapped": len(with_code),
        "unmapped": len(unmapped),
        "high_confidence": len(high),
        "medium_confidence": len(medium),
        "low_confidence": len(low),
        "top_taxonomy_codes": [{"code": c, "count": n} for c, n in top_buckets],
    }
