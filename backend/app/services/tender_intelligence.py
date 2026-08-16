"""TI-1 — Semantic Tender Intelligence (standards compliance + silence detection).

Combines Standards Engine library requirements with LLM semantic reasoning and
Knowledge Graph edges (gaps / conflicts_with). Gated by KNOWLEDGE_GRAPH_ENABLED.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import LanguageCode, RiskSeverity
from app.services.analyzer import RiskFinding, apply_composed_risk
from app.services.ontology_writer import upsert_ontology_edge
from app.services.standards_kg_bridge import link_finding_to_standard_clause
from app.standards_engine.compliance.semantic_compliance import (
    SemanticCoverageResult,
    check_requirements_semantic_batch,
)
from app.standards_engine.ingestion.pipeline import load_requirements_for_standard

logger = logging.getLogger(__name__)

TI_RISK_ID = "RISK-STD-CLAUSE-COMPLIANCE-001"

_STATUS_TO_SEVERITY = {
    "contradictory": RiskSeverity.HIGH,
    "silent": RiskSeverity.HIGH,
    "partial": RiskSeverity.MEDIUM,
}


def _titles(lang: LanguageCode) -> dict[str, dict[str, str]]:
    return {
        "silent": {
            LanguageCode.FA: "سکوت نسبت به الزام استاندارد — ریسک ادعا",
            LanguageCode.EN: "Silence vs standard requirement — claim risk",
            LanguageCode.DE: "Schweigen gegenüber Normanforderung — Claim-Risiko",
            LanguageCode.FR: "Silence vs exigence normative — risque de réclamation",
        },
        "partial": {
            LanguageCode.FA: "پوشش ناقص الزام استاندارد در اسناد مناقصه",
            LanguageCode.EN: "Incomplete tender coverage of standard requirement",
            LanguageCode.DE: "Unvollständige Ausschreibungsabdeckung der Norm",
            LanguageCode.FR: "Couverture incomplète de l'exigence normative",
        },
        "contradictory": {
            LanguageCode.FA: "تعارض معنایی با الزام استاندارد",
            LanguageCode.EN: "Semantic conflict with standard requirement",
            LanguageCode.DE: "Semantischer Konflikt mit Normanforderung",
            LanguageCode.FR: "Conflit sémantique avec exigence normative",
        },
    }


def _llm_not_configured_finding(lang: LanguageCode) -> RiskFinding:
    title = {
        LanguageCode.FA: "تحلیل معنایی استاندارد فعال نیست — کلید LLM پیکربندی نشده",
        LanguageCode.EN: "Semantic standards analysis unavailable — LLM not configured",
        LanguageCode.DE: "Semantische Standardanalyse nicht verfügbar — LLM nicht konfiguriert",
        LanguageCode.FR: "Analyse sémantique indisponible — LLM non configuré",
    }[lang]
    description = {
        LanguageCode.FA: (
            "TI-1 (تحلیل معنایی انطباق با استاندارد) نیاز به OPENAI_API_KEY یا "
            "LLM_PROVIDER=replay/local_semantic دارد. بدون آن، فقط تحلیل کلیدواژه‌ای اجرا می‌شود."
        ),
        LanguageCode.EN: (
            "TI-1 semantic compliance requires OPENAI_API_KEY or LLM_PROVIDER=replay/local_semantic. "
            "Without it, only the keyword analyzer runs for standards."
        ),
        LanguageCode.DE: "TI-1 benötigt OPENAI_API_KEY oder LLM_PROVIDER=replay/local_semantic.",
        LanguageCode.FR: "TI-1 nécessite OPENAI_API_KEY ou LLM_PROVIDER=replay/local_semantic.",
    }[lang]
    recommendation = {
        LanguageCode.FA: "OPENAI_API_KEY را در .env تنظیم کنید یا KNOWLEDGE_GRAPH_ENABLED=false بگذارید.",
        LanguageCode.EN: "Set OPENAI_API_KEY in .env or disable KNOWLEDGE_GRAPH_ENABLED.",
        LanguageCode.DE: "OPENAI_API_KEY in .env setzen oder KNOWLEDGE_GRAPH_ENABLED deaktivieren.",
        LanguageCode.FR: "Configurer OPENAI_API_KEY ou désactiver KNOWLEDGE_GRAPH_ENABLED.",
    }[lang]
    return RiskFinding(
        code="TI-LLM-NOT-CONFIGURED",
        category="process",
        severity=RiskSeverity.LOW,
        title=title,
        description=description,
        recommendation=recommendation,
        evidence="KNOWLEDGE_GRAPH_ENABLED=true but LLM not configured",
        finding_category="limitation",
        source_layer="python",
        cause_effect_chain=["source_layer=python", f"risk_id={TI_RISK_ID}", "ti_diagnostic=llm_not_configured"],
    )


def _finding_from_gap(
    gap: SemanticCoverageResult,
    *,
    lang: LanguageCode,
    index: int,
) -> RiskFinding:
    status = gap.coverage_status
    titles = _titles(lang)
    title = titles.get(status, titles["silent"]).get(lang, titles["silent"][LanguageCode.EN])
    severity = _STATUS_TO_SEVERITY.get(status, RiskSeverity.MEDIUM)

    desc_fa = (
        f"استاندارد {gap.standard_code} بند {gap.clause_number}: "
        f"{gap.requirement_text[:300]}\n\n"
        f"نتیجه تحلیل معنایی: {gap.reasoning}"
    )
    desc_en = (
        f"Standard {gap.standard_code} clause {gap.clause_number}: "
        f"{gap.requirement_text[:300]}\n\n"
        f"Semantic analysis: {gap.reasoning}"
    )
    description = desc_fa if lang == LanguageCode.FA else desc_en

    rec_fa = (
        "قبل از ابلاغ، مشخصات فنی/شرایط خصوصی را برای پوشش صریح این الزام "
        "بازبینی کنید یا تعارض را با کارفرما شفاف‌سازی کنید."
    )
    rec_en = (
        "Before award, revise specs/particular conditions to explicitly cover this "
        "requirement or clarify the conflict with the Employer."
    )
    recommendation = rec_fa if lang == LanguageCode.FA else rec_en

    evidence_parts = [
        f"standard={gap.standard_code}",
        f"clause={gap.clause_number}",
        f"requirement_id={gap.requirement_id}",
        f"coverage={gap.coverage_status}",
        gap.reasoning,
    ]
    if gap.tender_excerpt:
        evidence_parts.append(f"tender_excerpt={gap.tender_excerpt[:400]}")
    if gap.source_page is not None:
        evidence_parts.append(f"clause_source_page={gap.source_page}")

    source_layer = "llm_based"
    code = f"TI-STD-{gap.standard_code}-{gap.clause_number}-{index}".replace(" ", "-")[:64]

    if status in {"silent", "contradictory"}:
        fin_impact, sched_impact = "high", "medium"
    elif status == "partial":
        fin_impact, sched_impact = "medium", "low"
    else:
        fin_impact, sched_impact = None, None

    chain = [
        f"standard_code={gap.standard_code}",
        f"clause_number={gap.clause_number}",
        f"requirement_id={gap.requirement_id}",
        f"coverage_status={gap.coverage_status}",
        f"source_layer={source_layer}",
        f"risk_id={TI_RISK_ID}",
    ]
    if gap.source_page is not None:
        chain.append(f"clause_source_page={gap.source_page}")

    return apply_composed_risk(
        RiskFinding(
            code=code,
            category="compliance",
            severity=severity,
            title=title,
            description=description,
            recommendation=recommendation,
            evidence="\n".join(evidence_parts),
            source_excerpt=(gap.tender_excerpt or gap.requirement_text[:500]),
            finding_category="risk",
            source_layer=source_layer,
            confidence_score=75 if status == "silent" else 70,
            source_page=gap.source_page,
            cause_effect_chain=chain,
        ),
        likelihood=severity,
        financial_impact=fin_impact,
        schedule_impact=sched_impact,
        lang=lang,
    )


async def run_semantic_standards_compliance(
    db: AsyncSession,
    *,
    project_id: int,
    selected_standard_codes: list[str],
    document_corpus: str,
    lang: LanguageCode,
    max_checks_per_standard: int | None = None,
    llm: Any | None = None,
) -> tuple[list[RiskFinding], dict[str, Any]]:
    """
    TI-1 semantic compliance pass over ingested Standard requirements.

    Returns findings and metrics. Caller persists findings then calls
    ``link_ti_findings_to_graph`` for OntologyEdge rows.
    """
    corpus = (document_corpus or "").strip()
    cap = (
        max_checks_per_standard
        if max_checks_per_standard is not None
        else settings.ti_max_checks_per_standard
    )

    if not corpus or not selected_standard_codes:
        return [], {"enabled": True, "checks_run": 0, "gaps_found": 0, "llm_configured": True}

    all_gaps: list[tuple[SemanticCoverageResult, RiskFinding]] = []
    checks_run = 0
    llm_configured = True
    llm_provider: str | None = None

    for code in selected_standard_codes:
        _code, requirements = await load_requirements_for_standard(db, standard_code=code)
        if not requirements:
            continue
        subset_len = len(requirements) if cap <= 0 else min(len(requirements), cap)
        checks_run += subset_len
        gaps, batch_meta = check_requirements_semantic_batch(
            requirements,
            corpus,
            standard_code=code,
            max_checks=cap,
            llm=llm,
        )
        if not batch_meta.get("llm_configured", True):
            llm_configured = False
            metrics = {
                "enabled": True,
                "checks_run": 0,
                "gaps_found": 0,
                "llm_configured": False,
                "llm_error": batch_meta.get("error"),
                "standards_checked": selected_standard_codes,
            }
            return [_llm_not_configured_finding(lang)], metrics
        llm_provider = batch_meta.get("llm_provider")

        for idx, gap in enumerate(gaps):
            finding = _finding_from_gap(gap, lang=lang, index=idx + 1)
            all_gaps.append((gap, finding))

    findings = [f for _, f in all_gaps]
    metrics = {
        "enabled": True,
        "checks_run": checks_run,
        "gaps_found": len(findings),
        "standards_checked": selected_standard_codes,
        "llm_configured": llm_configured,
        "llm_provider": llm_provider,
        "max_checks_per_standard": cap,
    }
    return findings, metrics


async def link_ti_findings_to_graph(
    db: AsyncSession,
    *,
    project_id: int,
    finding_rows: list[Any],
    ti_findings: list[RiskFinding],
    document_id: int | None = None,
) -> int:
    """Link persisted TI findings to StandardClause + Requirement nodes."""
    linked = 0
    code_to_id = {getattr(row, "code", None): getattr(row, "id", None) for row in finding_rows}
    for f in ti_findings:
        if f.code == "TI-LLM-NOT-CONFIGURED":
            continue
        fid = code_to_id.get(f.code)
        if not fid:
            continue
        chain = f.cause_effect_chain or []
        req_id = None
        clause_num = None
        for bit in chain:
            if str(bit).startswith("requirement_id="):
                try:
                    req_id = int(str(bit).split("=", 1)[1])
                except ValueError:
                    pass
            if str(bit).startswith("clause_number="):
                clause_num = str(bit).split("=", 1)[1].strip()
        if req_id is None:
            continue
        from app.standards_engine.models import Requirement, StandardClause
        from sqlalchemy import select

        row = (
            await db.execute(
                select(StandardClause.id, StandardClause.source_page)
                .join(Requirement, Requirement.clause_id == StandardClause.id)
                .where(Requirement.id == req_id)
            )
        ).first()
        if row is None:
            continue
        clause_id, _clause_page = row
        predicate = "gaps"
        for bit in chain:
            if str(bit).startswith("coverage_status="):
                if str(bit).split("=", 1)[1].strip() == "contradictory":
                    predicate = "conflicts_with"
                break
        await link_finding_to_standard_clause(
            db,
            project_id=project_id,
            finding_id=int(fid),
            clause_id=int(clause_id),
            predicate=predicate,
            document_id=document_id,
            evidence={
                "finding_code": f.code,
                "requirement_id": req_id,
                "clause_number": clause_num,
                "source_layer": f.source_layer,
                "risk_id": TI_RISK_ID,
            },
        )
        await upsert_ontology_edge(
            db,
            project_id=project_id,
            from_type="Finding",
            from_id=int(fid),
            to_type="Requirement",
            to_id=req_id,
            predicate=predicate,
            confidence=80,
            origin_kind=f.source_layer or "llm_based",
            document_id=document_id,
            evidence={
                "finding_code": f.code,
                "requirement_id": req_id,
                "clause_number": clause_num,
            },
        )
        linked += 1
    return linked
