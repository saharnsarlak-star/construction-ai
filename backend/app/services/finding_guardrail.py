"""Part 5 evidence guardrail — reject or downgrade Med/High findings without evidence."""

from __future__ import annotations

import re
from typing import Any

from app.models import RiskSeverity
from app.services.analyzer import RiskFinding

_RISK_ID_RE = re.compile(r"risk_id=([A-Za-z0-9_\-]+)")


def _has_evidence(finding: RiskFinding) -> bool:
    for field in (
        finding.evidence,
        finding.source_excerpt,
        finding.source_document_name,
    ):
        if field and str(field).strip():
            return True
    return False


def _has_recommendation(finding: RiskFinding) -> bool:
    return bool((finding.recommendation or "").strip())


def _extract_risk_id(finding: RiskFinding) -> str | None:
    for bit in finding.cause_effect_chain or []:
        m = _RISK_ID_RE.search(str(bit))
        if m:
            rid = m.group(1).strip()
            if rid and rid.lower() not in {"none", "null", ""}:
                return rid
    return None


def _requires_risk_id(finding: RiskFinding) -> bool:
    layer = (finding.source_layer or "").strip().lower()
    return layer in {"rule_based", "llm_based", "hybrid"}


def apply_finding_guardrail(finding: RiskFinding) -> tuple[RiskFinding, dict[str, Any] | None]:
    """
    Apply Part 5 guardrail to a candidate finding before DB persist.

    Med/High risk findings without evidence, recommendation, or (when required) Risk ID
    are downgraded to ``limitation`` with ``data_completeness_caveat`` rather than dropped.
    """
    category = (finding.finding_category or "risk").strip().lower()
    if category != "risk":
        return finding, None

    sev = finding.severity
    sev_val = sev.value if hasattr(sev, "value") else str(sev)
    if sev_val not in {RiskSeverity.HIGH.value, RiskSeverity.MEDIUM.value}:
        return finding, None

    missing: list[str] = []
    if not _has_evidence(finding):
        missing.append("evidence")
    if not _has_recommendation(finding):
        missing.append("recommendation")
    if _requires_risk_id(finding) and not _extract_risk_id(finding):
        missing.append("risk_id")

    if not missing:
        return finding, None

    caveat = (
        "Finding downgraded by evidence guardrail: missing "
        + ", ".join(missing)
        + ". Review manually before treating as a confirmed commercial risk."
    )
    downgraded = RiskFinding(
        code=finding.code,
        category=finding.category,
        severity=RiskSeverity.LOW,
        title=finding.title,
        description=finding.description,
        recommendation=finding.recommendation or "Manual review required — insufficient evidence for automated Med/High risk.",
        financial_impact=finding.financial_impact,
        schedule_impact=finding.schedule_impact,
        evidence=finding.evidence or finding.source_excerpt,
        finding_category="limitation",
        risk_score=finding.risk_score,
        source_excerpt=finding.source_excerpt or finding.evidence,
        cause_effect_chain=list(finding.cause_effect_chain or []) + ["guardrail=downgraded"],
        data_completeness_caveat=caveat,
        estimated_impact=finding.estimated_impact,
        source_layer=finding.source_layer,
        confidence_score=finding.confidence_score,
        source_document_name=finding.source_document_name,
        source_page=finding.source_page,
    )
    meta = {
        "action": "downgraded",
        "original_severity": sev_val,
        "missing": missing,
        "code": finding.code,
    }
    return downgraded, meta


def apply_guardrails_to_findings(
    findings: list[RiskFinding],
) -> tuple[list[RiskFinding], list[dict[str, Any]]]:
    """Apply guardrail to each finding; return updated list and guardrail events."""
    out: list[RiskFinding] = []
    events: list[dict[str, Any]] = []
    for f in findings:
        updated, event = apply_finding_guardrail(f)
        out.append(updated)
        if event:
            events.append(event)
    return out, events
