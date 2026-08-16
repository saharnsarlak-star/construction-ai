"""Detect tender silence / weak coverage against structured standard requirements.

Legacy keyword overlap helper — used by ingestion CLI and STD-SEED-003 python pre-check.
Production analyze uses TI-1 semantic_compliance when TI_SEMANTIC_STANDARDS_ENABLED or KG is on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoverageGap:
    """One gap between a standard requirement and tender document text."""

    standard_code: str
    clause_number: str
    requirement_text: str
    gap_type: str  # silent | weak | ambiguous
    severity: str  # high | medium | low
    message_fa: str
    message_en: str
    topics: list[str] = field(default_factory=list)
    requirement_id: int | None = None
    matched_excerpt: str | None = None


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _tokens(text: str, *, min_len: int = 3) -> set[str]:
    norm = _normalize(text)
    return {w for w in re.findall(r"[\w\u0600-\u06ff]+", norm) if len(w) >= min_len}


def _overlap_score(requirement_text: str, tender_text: str) -> float:
    req_t = _tokens(requirement_text)
    if not req_t:
        return 0.0
    tender_t = _tokens(tender_text)
    if not tender_t:
        return 0.0
    hit = len(req_t & tender_t)
    return hit / len(req_t)


def check_requirement_coverage(
    requirement: dict[str, Any],
    tender_text: str,
    *,
    standard_code: str,
    clause_number: str,
    silent_threshold: float = 0.08,
    weak_threshold: float = 0.25,
) -> CoverageGap | None:
    """Return a gap if tender text poorly covers one requirement (keyword overlap heuristic)."""
    req_text = str(requirement.get("requirement_text") or "").strip()
    if not req_text:
        return None

    score = _overlap_score(req_text, tender_text)
    if score >= weak_threshold:
        return None

    gap_type = "silent" if score < silent_threshold else "weak"
    severity = "high" if gap_type == "silent" else "medium"
    topics = list(requirement.get("topic") or [])

    return CoverageGap(
        standard_code=standard_code,
        clause_number=clause_number,
        requirement_text=req_text,
        gap_type=gap_type,
        severity=severity,
        message_fa=(
            f"در اسناد مناقصه پوشش کافی برای الزام استاندارد {standard_code} "
            f"(بند {clause_number}) دیده نشد — ریسک سکوت/ابهام و ادعای مالی."
            if gap_type == "silent"
            else f"پوشش ضعیف برای الزام بند {clause_number} — نیاز به شفاف‌سازی."
        ),
        message_en=(
            f"Tender documents lack clear coverage for standard {standard_code} "
            f"clause {clause_number} — silence/ambiguity claim risk."
            if gap_type == "silent"
            else f"Weak tender coverage for clause {clause_number} — clarify before award."
        ),
        topics=topics,
        requirement_id=requirement.get("id"),
        matched_excerpt=None,
    )


def check_standard_coverage(
    requirements: list[dict[str, Any]],
    tender_text: str,
    *,
    standard_code: str,
    clause_numbers: dict[str, str] | None = None,
) -> list[CoverageGap]:
    """Check many requirements; ``clause_numbers`` maps requirement id → clause_number."""
    clause_numbers = clause_numbers or {}
    gaps: list[CoverageGap] = []
    for req in requirements:
        rid = req.get("id")
        clause_num = clause_numbers.get(rid) or req.get("clause_number") or "?"
        gap = check_requirement_coverage(
            req,
            tender_text,
            standard_code=standard_code,
            clause_number=str(clause_num),
        )
        if gap is not None:
            gaps.append(gap)
    return gaps
