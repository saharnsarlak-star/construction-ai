"""Phase 4 — [AI] and [HYBRID] seed rule runners (LLM behind AI_RULE_ENGINE_ENABLED)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import settings
from app.knowledge.country_profiles import get_country_profile
from app.knowledge.prompt_templates import resolve_prompt_template
from app.knowledge.rules_registry import RuleDef
from app.knowledge.seed_i18n import language_label
from app.knowledge.seed_rules_batch1 import build_seed_batch1_rules
from app.knowledge.seed_rules_batch2 import build_seed_batch2_rules
from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType, RiskSeverity
from app.services.analyzer import RiskFinding, _impact_label
from app.services.rule_engine.context import RuleContext, build_doc_view, ElementView
from app.services.rule_engine.hybrid_detectors import HybridDiscrepancy, detect_hybrid_discrepancy
from app.services.rule_engine.llm_client import LLMClient, LLMNotConfiguredError, LLMUsage

logger = logging.getLogger(__name__)

JSON_SCHEMA_HINT = """
Return ONLY a JSON object with keys:
{
  "triggered": boolean,  // true if this rule finding should be raised
  "confidence_score": number,  // 0-100
  "title": string,
  "description": string,  // include cause/effect claim risk
  "recommendation": string,
  "source_excerpt": string,  // EXACT quote from the provided excerpts (mandatory if triggered)
  "document_name": string,
  "location": string,  // clause/section/page/unit id if known
  "reasoning": string
}
Do not invent numeric quantities that contradict the excerpts.
Do not claim standards were re-parsed; reason only from provided context.
Write title, description, recommendation, and reasoning in the report language specified in the user payload.
Keep source_excerpt as an exact quote from the excerpts (do not translate quotes).
"""


def _llm_not_configured_finding(lang: LanguageCode) -> RiskFinding:
    title = {
        LanguageCode.FA: "موتور قوانین AI/HYBRID فعال نیست — LLM پیکربندی نشده",
        LanguageCode.EN: "AI/HYBRID rule engine unavailable — LLM not configured",
        LanguageCode.DE: "AI/HYBRID-Regelengine nicht verfügbar — LLM nicht konfiguriert",
        LanguageCode.FR: "Moteur de règles AI/HYBRID indisponible — LLM non configuré",
    }[lang]
    description = {
        LanguageCode.FA: (
            "AI_RULE_ENGINE_ENABLED=true است اما OPENAI_API_KEY یا "
            "LLM_PROVIDER=replay/local_semantic تنظیم نشده است."
        ),
        LanguageCode.EN: (
            "AI_RULE_ENGINE_ENABLED is true but OPENAI_API_KEY or "
            "LLM_PROVIDER=replay/local_semantic is not configured."
        ),
        LanguageCode.DE: "AI_RULE_ENGINE_ENABLED ist true, aber kein LLM konfiguriert.",
        LanguageCode.FR: "AI_RULE_ENGINE_ENABLED est true mais aucun LLM configuré.",
    }[lang]
    return RiskFinding(
        code="AI-LLM-NOT-CONFIGURED",
        category="process",
        severity=RiskSeverity.LOW,
        title=title,
        description=description,
        recommendation="Set OPENAI_API_KEY or LLM_PROVIDER=local_semantic for offline tests.",
        evidence="AI_RULE_ENGINE_ENABLED=true without LLM provider",
        finding_category="limitation",
        source_layer="python",
        cause_effect_chain=["source_layer=python", "ai_diagnostic=llm_not_configured"],
    )


def list_ai_hybrid_seed_rules() -> list[RuleDef]:
    rules = build_seed_batch1_rules() + build_seed_batch2_rules()
    return [
        r
        for r in rules
        if (r.logic_config or {}).get("ownership_tag") in {"AI", "HYBRID"}
    ]


def run_ai_hybrid_seed_rules(
    *,
    country: CountryCode | str,
    report_language: LanguageCode,
    documents: list[dict[str, Any]],
    project_type: ProjectType | str | None = None,
    selected_standards: list[dict[str, Any]] | None = None,
    standard_requirements: list[dict[str, Any]] | None = None,
    elements: list[dict[str, Any]] | list[ElementView] | None = None,
    project_id: int | None = None,
    llm: LLMClient | None = None,
    rkb_catalog: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[RiskFinding], dict[str, Any]]:
    """
    Run [AI] + [HYBRID] seed rules.
    HYBRID: Python discrepancy first; LLM only explains if discrepancy exists.
    Returns (findings, metrics) with cost/latency totals.
    When rkb_catalog is provided (Phase 6), risk_id mapping uses the DB snapshot.
    """
    from app.services.rule_engine.runners import set_rkb_catalog

    if rkb_catalog is not None:
        set_rkb_catalog(rkb_catalog)
    else:
        set_rkb_catalog(None)

    try:
        return _run_ai_hybrid_seed_rules_inner(
            country=country,
            report_language=report_language,
            documents=documents,
            project_type=project_type,
            selected_standards=selected_standards,
            standard_requirements=standard_requirements,
            elements=elements,
            project_id=project_id,
            llm=llm,
        )
    finally:
        set_rkb_catalog(None)


def _run_ai_hybrid_seed_rules_inner(
    *,
    country: CountryCode | str,
    report_language: LanguageCode,
    documents: list[dict[str, Any]],
    project_type: ProjectType | str | None = None,
    selected_standards: list[dict[str, Any]] | None = None,
    standard_requirements: list[dict[str, Any]] | None = None,
    elements: list[dict[str, Any]] | list[ElementView] | None = None,
    project_id: int | None = None,
    llm: LLMClient | None = None,
) -> tuple[list[RiskFinding], dict[str, Any]]:
    if isinstance(country, str):
        country = CountryCode(country)
    if isinstance(project_type, str):
        try:
            project_type = ProjectType(project_type)
        except ValueError:
            project_type = ProjectType.INFRASTRUCTURE
    ptype = project_type or ProjectType.INFRASTRUCTURE

    element_views: list[ElementView] = []
    for el in elements or []:
        if isinstance(el, ElementView):
            element_views.append(el)
        elif isinstance(el, dict):
            element_views.append(
                ElementView(
                    id=int(el.get("id") or 0),
                    element_type=str(el.get("element_type") or "element"),
                    name_label=el.get("name_label"),
                    type_mark=el.get("type_mark"),
                    ifc_global_id=el.get("ifc_global_id"),
                    match_key=str(el.get("match_key") or ""),
                    document_ids=list(el.get("document_ids") or []),
                )
            )

    ctx = RuleContext(
        project_id=project_id,
        country=country.value,
        project_type=ptype,
        documents=[build_doc_view(d) for d in documents],
        selected_standards=selected_standards or [],
        standard_requirements=list(standard_requirements or []),
        elements=element_views,
    )
    client = llm or LLMClient()
    metrics: dict[str, Any] = {
        "provider": client.provider,
        "model": client.model,
        "calls": 0,
        "skipped_no_llm": 0,
        "skipped_no_discrepancy": 0,
        "skipped_no_excerpt": 0,
        "skipped_missing_category": 0,
        "hybrid_python_hits": 0,
        "total_latency_ms": 0.0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "estimated_cost_usd": 0.0,
        "per_call": [],
    }
    if not client.is_configured:
        metrics["error"] = "LLM not configured (set OPENAI_API_KEY or LLM_PROVIDER=replay/local_semantic)"
        metrics["llm_configured"] = False
        return [_llm_not_configured_finding(report_language)], metrics

    metrics["llm_configured"] = True
    findings: list[RiskFinding] = []
    cap = int(settings.ai_max_calls_per_analysis or 0)
    max_calls = cap if cap > 0 else len(list_ai_hybrid_seed_rules()) + 1

    for rule in list_ai_hybrid_seed_rules():
        if metrics["calls"] >= max_calls:
            metrics["truncated"] = True
            break
        req = rule.requires_category
        check = str((rule.logic_config or {}).get("check") or "")
        # TI-1 owns semantic standard compliance when TI is active (Phase C)
        if settings.ti_semantic_active and check == "standard_clause_semantic_compliance":
            metrics["skipped_ti1_active"] = int(metrics.get("skipped_ti1_active") or 0) + 1
            continue
        if req is not None and not ctx.docs(req):
            if not (req == DocumentCategory.STANDARD and ctx.selected_standards):
                metrics["skipped_missing_category"] = int(metrics.get("skipped_missing_category") or 0) + 1
                continue
        tag = str((rule.logic_config or {}).get("ownership_tag") or "")
        try:
            if tag == "HYBRID":
                disc = detect_hybrid_discrepancy(check, ctx)
                if disc is None:
                    metrics["skipped_no_discrepancy"] += 1
                    continue
                metrics["hybrid_python_hits"] += 1
                finding, usage = _run_hybrid_explain(
                    rule, ctx, disc, client, country, report_language, ptype
                )
            else:
                pack = _excerpt_pack_for_ai_rule(check, ctx)
                if not pack.get("excerpts"):
                    metrics["skipped_no_excerpt"] += 1
                    continue
                finding, usage = _run_ai_rule(
                    rule, ctx, pack, client, country, report_language, ptype
                )
        except LLMNotConfiguredError:
            metrics["skipped_no_llm"] += 1
            break
        except Exception:  # noqa: BLE001
            logger.exception("AI/HYBRID runner failed for %s", rule.code)
            continue

        metrics["calls"] += 1
        _accumulate_usage(metrics, usage, rule.code, check, tag)
        if finding is not None:
            findings.append(finding)

    # Per-document rollup for feasibility
    doc_count = max(1, len(ctx.documents))
    metrics["per_document"] = {
        "avg_latency_ms": round(metrics["total_latency_ms"] / doc_count, 1),
        "avg_cost_usd": round(metrics["estimated_cost_usd"] / doc_count, 6),
        "calls_per_document": round(metrics["calls"] / doc_count, 2),
    }
    return findings, metrics


def _accumulate_usage(metrics: dict[str, Any], usage: LLMUsage, code: str, check: str, tag: str) -> None:
    metrics["total_latency_ms"] = round(metrics["total_latency_ms"] + usage.latency_ms, 1)
    metrics["total_prompt_tokens"] += usage.prompt_tokens
    metrics["total_completion_tokens"] += usage.completion_tokens
    metrics["estimated_cost_usd"] = round(metrics["estimated_cost_usd"] + usage.estimated_cost_usd, 6)
    metrics["per_call"].append(
        {
            "code": code,
            "check": check,
            "tag": tag,
            "latency_ms": usage.latency_ms,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "estimated_cost_usd": usage.estimated_cost_usd,
        }
    )


def _run_hybrid_explain(
    rule: RuleDef,
    ctx: RuleContext,
    disc: HybridDiscrepancy,
    client: LLMClient,
    country: CountryCode,
    lang: LanguageCode,
    ptype: ProjectType,
) -> tuple[RiskFinding | None, LLMUsage]:
    system = (
        "You are an employer-side construction tender risk analyst. "
        "A deterministic Python check ALREADY detected a discrepancy. "
        "Your job is ONLY to explain claim/delay/cost risk and recommend actions. "
        "Do NOT re-detect or invent a different discrepancy. "
        "Use the Python discrepancy as ground truth. "
        f"Write title, description, recommendation, and reasoning in {language_label(lang)}."
        + JSON_SCHEMA_HINT
    )
    user = _user_payload(
        rule=rule,
        country=country,
        ptype=ptype,
        mode="hybrid_explain",
        lang=lang,
        excerpts=disc.excerpts,
        extra={
            "python_discrepancy_summary": disc.summary,
            "python_evidence": disc.evidence,
            "python_metrics": disc.metrics,
            "ontology_entities": (rule.logic_config or {}).get("ontology_entities") or [],
        },
    )
    resp = client.chat_json(system=system, user=user, call_key=rule.code)
    finding = _finding_from_llm(rule, lang, resp.parsed, source_layer="hybrid", fallback_excerpt=disc.excerpts)
    if finding and not finding.evidence:
        finding.evidence = disc.evidence
    return finding, resp.usage


def _run_ai_rule(
    rule: RuleDef,
    ctx: RuleContext,
    pack: dict[str, Any],
    client: LLMClient,
    country: CountryCode,
    lang: LanguageCode,
    ptype: ProjectType,
) -> tuple[RiskFinding | None, LLMUsage]:
    # Reuse country prompt pack when analyzing responsibility
    try:
        tmpl = resolve_prompt_template(
            code="ANALYZE_RESPONSIBILITY_CLAUSES", country=country, project_type=ptype
        )
        system_base = tmpl.system_prompt
        context_pack = tmpl.context_pack
    except Exception:  # noqa: BLE001
        system_base = "You are an employer-side construction tender risk analyst."
        context_pack = {}

    system = (
        system_base
        + " Analyze ONLY for the specific seed rule described. "
        "If the excerpts do not support the rule, set triggered=false. "
        f"Write title, description, recommendation, and reasoning in {language_label(lang)}."
        + JSON_SCHEMA_HINT
    )
    user = _user_payload(
        rule=rule,
        country=country,
        ptype=ptype,
        mode="ai_detect",
        lang=lang,
        excerpts=pack.get("excerpts") or [],
        extra={
            "focus_hints": pack.get("focus_hints") or [],
            "ontology_entities": (rule.logic_config or {}).get("ontology_entities") or [],
            "context_pack": context_pack,
            "element_registry": [
                {
                    "id": e.id,
                    "type": e.element_type,
                    "mark": e.type_mark or e.name_label,
                    "ifc": e.ifc_global_id,
                }
                for e in (ctx.elements or [])[:20]
            ],
        },
    )
    resp = client.chat_json(system=system, user=user, call_key=rule.code)
    finding = _finding_from_llm(
        rule, lang, resp.parsed, source_layer="llm_based", fallback_excerpt=pack.get("excerpts") or []
    )
    return finding, resp.usage


def _user_payload(
    *,
    rule: RuleDef,
    country: CountryCode,
    ptype: ProjectType,
    mode: str,
    excerpts: list[dict[str, str]],
    extra: dict[str, Any],
    lang: LanguageCode = LanguageCode.EN,
) -> str:
    profile = get_country_profile(country)
    title = rule.title.get(lang) or rule.title.get(LanguageCode.EN) or next(iter(rule.title.values()))
    desc = (
        rule.description.get(lang)
        or rule.description.get(LanguageCode.EN)
        or next(iter(rule.description.values()))
    )
    body = {
        "mode": mode,
        "report_language": lang.value,
        "report_language_name": language_label(lang),
        "rule": {
            "code": rule.code,
            "check": (rule.logic_config or {}).get("check"),
            "risk_id": (rule.logic_config or {}).get("risk_id"),
            "ownership_tag": (rule.logic_config or {}).get("ownership_tag"),
            "title": title,
            "description": desc,
            "severity": rule.severity.value,
        },
        "project": {"country": country.value, "project_type": ptype.value, "profile": profile.code},
        "excerpts": excerpts[:12],
        **extra,
    }
    return json.dumps(body, ensure_ascii=False, indent=2)


def _finding_from_llm(
    rule: RuleDef,
    lang: LanguageCode,
    parsed: dict[str, Any] | None,
    *,
    source_layer: str,
    fallback_excerpt: list[dict[str, str]],
) -> RiskFinding | None:
    from app.knowledge.rkb import apply_rkb_to_finding_fields
    from app.services.rule_engine.runners import _lookup_risk

    if not parsed or not parsed.get("triggered"):
        return None
    conf = parsed.get("confidence_score")
    try:
        conf_i = int(round(float(conf)))
        conf_i = max(0, min(100, conf_i))
    except (TypeError, ValueError):
        conf_i = 60

    excerpt = str(parsed.get("source_excerpt") or "").strip()
    if not excerpt and fallback_excerpt:
        excerpt = str(fallback_excerpt[0].get("text") or "")[:500]
    if not excerpt:
        # Part 5 requires source_excerpt for AI findings — skip if model omitted quote
        return None

    doc_name = str(parsed.get("document_name") or (fallback_excerpt[0].get("document") if fallback_excerpt else "") or "")
    location = str(parsed.get("location") or "")
    loc_bit = f" [{location}]" if location else ""
    doc_bit = f" ({doc_name})" if doc_name else ""

    title = str(parsed.get("title") or rule.title.get(lang) or rule.title.get(LanguageCode.EN) or rule.code)
    description = str(
        parsed.get("description")
        or rule.description.get(lang)
        or rule.description.get(LanguageCode.EN)
        or ""
    )
    default_rec = {
        LanguageCode.FA: "قبل از ابلاغ مناقصه شفاف‌سازی کنید.",
        LanguageCode.EN: "Clarify before tender award.",
        LanguageCode.DE: "Vor Zuschlag klarstellen.",
        LanguageCode.FR: "Clarifier avant attribution.",
    }.get(lang, "Clarify before tender award.")
    recommendation = str(
        parsed.get("recommendation")
        or rule.recommendation.get(lang)
        or rule.recommendation.get(LanguageCode.EN)
        or default_rec
    )
    reasoning = str(parsed.get("reasoning") or "")
    reasoning_prefix = {
        LanguageCode.FA: "استدلال",
        LanguageCode.EN: "Reasoning",
        LanguageCode.DE: "Begründung",
        LanguageCode.FR: "Raisonnement",
    }.get(lang, "Reasoning")

    risk_id = str((rule.logic_config or {}).get("risk_id") or "")
    risk = _lookup_risk(risk_id)
    enriched = apply_rkb_to_finding_fields(
        risk=risk,
        financial_impact=rule.financial_impact,
        schedule_impact=rule.schedule_impact,
        recommendation=recommendation,
        lang=lang,
    )
    mapping_src = enriched.get("mapping_source") or (risk or {}).get("mapping_source") or (risk or {}).get("source") or "python_seed"

    from app.services.analyzer import apply_composed_risk, parse_source_page

    return apply_composed_risk(
        RiskFinding(
            code=rule.code,
            category=rule.category,
            severity=rule.severity if conf_i >= 40 else RiskSeverity.MEDIUM,
            title=title,
            description=description + (f" {reasoning_prefix}: {reasoning}" if reasoning else ""),
            recommendation=enriched["recommendation"] or recommendation,
            evidence=f"{doc_bit.strip()}{loc_bit}: {excerpt}"[:2000],
            finding_category="risk",
            source_excerpt=excerpt[:800],
            source_document_name=doc_name or None,
            source_page=parse_source_page(location),
            cause_effect_chain=[
                f"risk_id={risk_id or enriched.get('risk_id')}",
                f"check={(rule.logic_config or {}).get('check')}",
                f"source_layer={source_layer}",
                f"rkb_source={mapping_src}",
                f"confidence_score={conf_i}",
                f"document={doc_name}",
                f"location={location}",
                "score_model=likelihood×impact",
            ],
            source_layer=source_layer,
            confidence_score=conf_i,
        ),
        likelihood=conf_i if conf_i else rule.severity,
        financial_impact=enriched.get("financial_impact") or rule.financial_impact,
        schedule_impact=enriched.get("schedule_impact") or rule.schedule_impact,
        lang=lang,
    )


# ----- AI excerpt packing (relevant CDM / text windows) -----


_AI_FOCUS: dict[str, list[str]] = {
    "contract_responsibility_ambiguity": [
        r"\bif necessary\b",
        r"\bas required\b",
        r"\breasonable\b",
        r"\bemployer\b.*\bcontractor\b",
        r"\bshall\b.*\bmay\b",
        r"\bresponsibility\b",
        r"\bliability\b",
        r"\bindemnif",
        r"\bdrainage\b",
    ],
    "contract_bond_ambiguity": [
        r"\bbond\b",
        r"\bguarantee\b",
        r"\bperformance\s+security\b",
        r"\bretention\b",
        r"\bwarranty\b",
    ],
    "specs_missing_sensitive_grades": [
        r"\bconcrete\b",
        r"\bsteel\b",
        r"\brebar\b",
        r"\bweld",
        r"\bgrade\b",
        r"\bC\d{2}/",
    ],
    "drawing_missing_connection_detail": [
        r"\bconnection\b",
        r"\bdetail\b",
        r"\bjoint\b",
        r"\btypical\b",
    ],
    "drawing_plan_vs_section": [r"\bplan\b", r"\bsection\b", r"\belevation\b"],
    "itt_evaluation_unclear": [
        r"\bevaluation\b",
        r"\bscoring\b",
        r"\btechnical\s+weight\b",
        r"\bfinancial\s+weight\b",
        r"\bcriteria\b",
    ],
    "geotech_groundwater_content": [r"\bgroundwater\b", r"\bwater\s+table\b", r"\borehole\b"],
    "er_vague_performance": [
        r"\bhigh\s+quality\b",
        r"\bas\s+required\b",
        r"\bif\s+necessary\b",
        r"\breasonable\b",
        r"\bworld[- ]class\b",
        r"\bperformance\b",
    ],
    "addendum_implicit_contradiction": [r"\baddendum\b", r"\binstead\b", r"\breplace\b", r"\bsupersed"],
}


def _excerpt_pack_for_ai_rule(check: str, ctx: RuleContext) -> dict[str, Any]:
    patterns = _AI_FOCUS.get(check) or [r"\bshall\b"]
    excerpts: list[dict[str, str]] = []
    for d in ctx.documents:
        text = d.extracted_text or ""
        # Prefer CDM content units when present
        units = d.canonical.get("content_units") if isinstance(d.canonical.get("content_units"), list) else []
        candidates: list[tuple[str, str]] = []
        for u in units:
            if isinstance(u, dict) and u.get("text"):
                loc = f"unit={u.get('id')}; page={u.get('page_or_sheet')}"
                candidates.append((str(u["text"]), loc))
        if not candidates:
            # paragraph windows
            for i, para in enumerate(re.split(r"\n\s*\n+", text)[:80]):
                if para.strip():
                    candidates.append((para.strip(), f"para={i+1}"))

        for para, loc in candidates:
            if any(re.search(p, para, re.I) for p in patterns):
                excerpts.append(
                    {
                        "document": d.original_name,
                        "document_id": str(d.id or ""),
                        "location": loc,
                        "text": para[:900],
                        "category": d.category.value,
                        "subtype": d.subtype,
                    }
                )
            if len(excerpts) >= 8:
                break
        if len(excerpts) >= 8:
            break

    # Always include a short head of tender if still empty but docs exist
    if not excerpts and ctx.documents:
        d = ctx.documents[0]
        excerpts.append(
            {
                "document": d.original_name,
                "document_id": str(d.id or ""),
                "location": "head",
                "text": (d.extracted_text or "")[:1200],
                "category": d.category.value,
            }
        )
    return {"excerpts": excerpts, "focus_hints": patterns}
