"""Semantic (LLM) compliance checking — Standards Engine requirements vs tender text.

Uses meaning-based reasoning, not keyword overlap (business requirement #2, #7).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.rule_engine.llm_client import LLMClient, LLMNotConfiguredError

logger = logging.getLogger(__name__)

_MAX_LLM_ATTEMPTS = 4
_RETRY_BACKOFF = (2, 4, 8)


@dataclass
class SemanticCoverageResult:
    requirement_id: int | None
    clause_number: str
    standard_code: str
    requirement_text: str
    coverage_status: str  # covered | partial | silent | contradictory
    severity: str
    reasoning: str
    tender_excerpt: str | None = None
    source_page: int | None = None
    topics: list[str] = field(default_factory=list)


def _call_llm_json(client: LLMClient, *, system: str, user: str, call_key: str) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
        try:
            resp = client.chat_json(system=system, user=user, call_key=call_key, temperature=0.0)
            return resp.parsed or {}
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt >= _MAX_LLM_ATTEMPTS:
                raise
            time.sleep(_RETRY_BACKOFF[attempt - 1])
    if last_exc:
        raise last_exc
    return {}


def _build_prompt(
    *,
    standard_code: str,
    clause_number: str,
    requirement: dict[str, Any],
    tender_excerpt: str,
) -> tuple[str, str]:
    system = (
        "You are a construction tender compliance analyst. Compare a regulatory standard "
        "requirement against tender document text by MEANING — not keyword matching. "
        "Two texts may express the same obligation with completely different wording. "
        "Return ONLY valid JSON."
    )
    payload = {
        "task": "semantic_standard_compliance_check",
        "standard_code": standard_code,
        "clause_number": clause_number,
        "requirement": {
            "text": requirement.get("requirement_text"),
            "type": requirement.get("requirement_type"),
            "min_value": requirement.get("min_value"),
            "max_value": requirement.get("max_value"),
            "unit": requirement.get("unit"),
        },
        "tender_excerpt": tender_excerpt[:6000],
        "output_schema": {
            "coverage_status": "covered | partial | silent | contradictory",
            "severity": "high | medium | low",
            "reasoning": "short explanation in English",
            "tender_excerpt": "short quote from tender if any support (or null)",
        },
        "rules": [
            "covered = tender clearly addresses the same technical obligation (even if different words)",
            "partial = tender mentions related topic but missing key parameters or conditions",
            "silent = tender does not address this obligation — claim/silence risk",
            "contradictory = tender conflicts with the standard requirement",
        ],
    }
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    return system, user


def _relevant_tender_excerpt(tender_text: str, requirement_text: str, *, window: int = 2500) -> str:
    """Select a focused tender excerpt for LLM (topic-aware slice, not full corpus)."""
    text = (tender_text or "").strip()
    if len(text) <= window * 2:
        return text

    # Simple anchor: find numeric tokens from requirement in tender
    import re

    nums = re.findall(r"\d+(?:\.\d+)?", requirement_text or "")
    for num in nums[:5]:
        idx = text.find(num)
        if idx >= 0:
            start = max(0, idx - window)
            end = min(len(text), idx + window)
            return text[start:end]

    # Fallback: head + tail
    return text[:window] + "\n...\n" + text[-window:]


def check_requirement_semantic(
    requirement: dict[str, Any],
    tender_text: str,
    *,
    standard_code: str,
    clause_number: str,
    llm: LLMClient | None = None,
) -> SemanticCoverageResult | None:
    """LLM semantic coverage check for one requirement."""
    req_text = str(requirement.get("requirement_text") or "").strip()
    if not req_text:
        return None

    client = llm or LLMClient()
    excerpt = _relevant_tender_excerpt(tender_text, req_text)
    system, user = _build_prompt(
        standard_code=standard_code,
        clause_number=clause_number,
        requirement=requirement,
        tender_excerpt=excerpt,
    )
    rid = requirement.get("id")
    call_key = f"ti_semantic_{standard_code}_{clause_number}_{rid}"

    try:
        parsed = _call_llm_json(client, system=system, user=user, call_key=call_key)
    except LLMNotConfiguredError:
        return None

    status = str(parsed.get("coverage_status") or "silent").strip().lower()
    if status not in {"partial", "silent", "contradictory"}:
        return None

    severity = str(parsed.get("severity") or ("high" if status in {"silent", "contradictory"} else "medium"))
    if severity not in {"high", "medium", "low"}:
        severity = "medium"

    return SemanticCoverageResult(
        requirement_id=int(rid) if rid is not None else None,
        clause_number=clause_number,
        standard_code=standard_code,
        requirement_text=req_text,
        coverage_status=status,
        severity=severity,
        reasoning=str(parsed.get("reasoning") or "").strip(),
        tender_excerpt=(str(parsed.get("tender_excerpt")).strip() if parsed.get("tender_excerpt") else None),
        source_page=requirement.get("source_page"),
        topics=list(requirement.get("topic") or []),
    )


def check_requirements_semantic_batch(
    requirements: list[dict[str, Any]],
    tender_text: str,
    *,
    standard_code: str,
    max_checks: int = 0,
    llm: LLMClient | None = None,
) -> tuple[list[SemanticCoverageResult], dict[str, Any]]:
    """
    Run semantic checks on requirements (cost control via ``max_checks``; 0 = all).

    Returns (gaps, metrics) where metrics includes ``llm_configured`` flag.
    """
    client = llm or LLMClient()
    if not client.is_configured:
        return [], {
            "llm_configured": False,
            "checks_attempted": 0,
            "error": "OPENAI_API_KEY not set and LLM_PROVIDER is not replay/local_semantic",
        }

    subset = requirements if max_checks <= 0 else requirements[:max_checks]
    results: list[SemanticCoverageResult] = []
    for req in subset:
        clause_number = str(req.get("clause_number") or "?")
        hit = check_requirement_semantic(
            req,
            tender_text,
            standard_code=standard_code,
            clause_number=clause_number,
            llm=client,
        )
        if hit is not None:
            results.append(hit)
    return results, {
        "llm_configured": True,
        "checks_attempted": len(subset),
        "llm_provider": client.provider,
    }
