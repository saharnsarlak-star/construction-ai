"""Deterministic check implementations for [PYTHON] seed rules only."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from app.knowledge.rules_registry import RuleDef
from app.knowledge.standards_catalog import (
    applicability_level,
    list_standards_for_country,
)
from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType, RiskSeverity
from app.services.analyzer import RiskFinding
from app.services.rule_engine.context import (
    RuleContext,
    extract_dates,
    extract_labeled_date,
)

Runner = Callable[[RuleDef, RuleContext, LanguageCode], list[RiskFinding]]

# Phase 6: optional in-process RKB catalog override (DB snapshot). None → Python seed dicts.
_RKB_CATALOG: dict[str, dict] | None = None


def set_rkb_catalog(catalog: dict[str, dict] | None) -> None:
    global _RKB_CATALOG
    _RKB_CATALOG = catalog


def _lookup_risk(risk_id: str | None) -> dict | None:
    from app.knowledge.rkb import python_risk_catalog

    if not risk_id:
        return None
    if _RKB_CATALOG is not None:
        return _RKB_CATALOG.get(risk_id)
    return python_risk_catalog().get(risk_id)


def _L(rule: RuleDef, lang: LanguageCode, field: str) -> str:
    mp = getattr(rule, field)
    return mp.get(lang) or mp.get(LanguageCode.EN) or next(iter(mp.values()))


def _finding(
    rule: RuleDef,
    lang: LanguageCode,
    *,
    evidence: str,
    description: str | None = None,
    recommendation: str | None = None,
    risk_score: int | None = None,
) -> RiskFinding:
    from app.knowledge.rkb import apply_rkb_to_finding_fields
    from app.services.analyzer import apply_composed_risk

    # risk_score from a runner is a detection/likelihood prior (0–100), not final priority.
    # Final score = likelihood × max(financial, schedule) — see compose_finding_risk.
    likelihood: object = risk_score if risk_score is not None else rule.severity
    risk_id = str((rule.logic_config or {}).get("risk_id") or "")
    risk = _lookup_risk(risk_id)
    # User-facing title/description always follow report language.
    # Runner-provided English detail stays in evidence only.
    localized_desc = _L(rule, lang, "description")
    evidence_parts = [evidence.strip()] if evidence and evidence.strip() else []
    if description and description.strip() and description.strip() != localized_desc:
        evidence_parts.append(description.strip())
    merged_evidence = "\n".join(evidence_parts)[:2000]
    enriched = apply_rkb_to_finding_fields(
        risk=risk,
        financial_impact=rule.financial_impact,
        schedule_impact=rule.schedule_impact,
        recommendation=recommendation or _L(rule, lang, "recommendation"),
        lang=lang,
    )
    mapping_src = enriched.get("mapping_source") or ("rkb_db" if _RKB_CATALOG is not None else "python_seed")
    return apply_composed_risk(
        RiskFinding(
            code=rule.code,
            category=rule.category,
            severity=rule.severity,
            title=_L(rule, lang, "title"),
            description=localized_desc,
            recommendation=enriched["recommendation"] or _L(rule, lang, "recommendation"),
            evidence=merged_evidence,
            finding_category="risk",
            source_excerpt=merged_evidence[:500],
            source_document_name=_extract_doc_names_from_text(merged_evidence),
            cause_effect_chain=[
                f"risk_id={risk_id or enriched.get('risk_id')}",
                f"check={(rule.logic_config or {}).get('check')}",
                "source_layer=rule_based",
                f"rkb_source={mapping_src}",
                "score_model=likelihood×impact",
            ],
            source_layer="rule_based",
        ),
        likelihood=likelihood,
        financial_impact=enriched.get("financial_impact") or rule.financial_impact,
        schedule_impact=enriched.get("schedule_impact") or rule.schedule_impact,
        lang=lang,
    )


def _extract_doc_names_from_text(text: str | None) -> str | None:
    if not text:
        return None
    found: list[str] = []
    for m in re.finditer(r"([\w.\-]+\.(?:pdf|docx?|xlsx?|txt|dwg|dxf|ifc|x8\d|d8\d))", text, re.I):
        name = m.group(1)
        if name not in found:
            found.append(name)
        if len(found) >= 4:
            break
    return "، ".join(found) if found else None


# ----- Schedule -----


def schedule_orphan_activity(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    acts = ctx.activities()
    if len(acts) < 2:
        return []
    ids = {a.activity_id for a in acts}
    orphans = []
    for a in acts:
        if a.is_milestone:
            continue
        preds = [p for p in a.predecessors if p in ids]
        succs = [s for s in a.successors if s in ids]
        if not preds and not succs:
            orphans.append(a)
    if not orphans:
        return []
    sample = ", ".join(f"{o.activity_id} ({o.name})" for o in orphans[:8])
    return [
        _finding(
            rule,
            lang,
            evidence=(
                f"{len(orphans)} island/floating activities of {len(acts)} total in "
                f"{orphans[0].document_name or 'schedule'}: {sample}"
            ),
            description=(
                f"Detected {len(orphans)} non-milestone activities with neither predecessor nor "
                f"successor among {len(acts)} parsed activities. Examples: {sample}."
            ),
            risk_score=60,
        )
    ]


def schedule_invalid_duration(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    bad = [
        a
        for a in ctx.activities()
        if (not a.is_milestone) and a.duration_days is not None and a.duration_days <= 0
    ]
    if not bad:
        return []
    detail = "; ".join(f"{a.activity_id} duration={a.duration_days}" for a in bad[:10])
    return [
        _finding(
            rule,
            lang,
            evidence=detail,
            description=(
                f"{len(bad)} non-milestone activities have duration ≤ 0. Details: {detail}."
            ),
            risk_score=85,
        )
    ]


def schedule_end_before_start(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    bad = [a for a in ctx.activities() if a.start and a.finish and a.finish < a.start]
    if not bad:
        return []
    detail = "; ".join(
        f"{a.activity_id} start={a.start.isoformat()} finish={a.finish.isoformat()}" for a in bad[:10]
    )
    return [
        _finding(
            rule,
            lang,
            evidence=detail,
            description=f"{len(bad)} activities have finish < start. Details: {detail}.",
            risk_score=85,
        )
    ]


def schedule_negative_float(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    bad = [a for a in ctx.activities() if a.total_float is not None and a.total_float < 0]
    if not bad:
        return []
    detail = "; ".join(f"{a.activity_id} float={a.total_float}" for a in bad[:10])
    return [
        _finding(
            rule,
            lang,
            evidence=detail,
            description=f"{len(bad)} activities have negative total float. Details: {detail}.",
            risk_score=80,
        )
    ]


def schedule_vs_contract_ntp(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    sched_text = ctx.text_blob(DocumentCategory.SCHEDULE)
    tender_text = ctx.text_blob(DocumentCategory.TENDER)
    if not sched_text or not tender_text:
        return []
    sched_start = extract_labeled_date(
        sched_text,
        ["programme start", "project start", "data date", "schedule start", "commencement"],
    )
    if sched_start is None:
        acts = [a for a in ctx.activities() if a.start]
        if acts:
            sched_start = min(a.start for a in acts if a.start)
    ntp = extract_labeled_date(
        tender_text,
        [
            "notice to proceed",
            "ntp",
            "commencement date",
            "start date",
            "contract commencement",
        ],
    )
    if not sched_start or not ntp:
        return []
    delta = abs((sched_start - ntp).days)
    if delta <= 1:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence=(
                f"schedule_start={sched_start.isoformat()} ntp/commencement={ntp.isoformat()} "
                f"delta_days={delta}"
            ),
            description=(
                f"Programme start ({sched_start.isoformat()}) differs from contract NTP/"
                f"commencement ({ntp.isoformat()}) by {delta} days."
            ),
            risk_score=75,
        )
    ]


def schedule_missing_resources(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    acts = ctx.activities()
    if not acts:
        return []
    # Only fire when at least one activity has resources (schema provides them)
    if not any(a.resources for a in acts):
        return []
    main = sorted(
        [a for a in acts if not a.is_milestone],
        key=lambda a: (a.duration_days or 0),
        reverse=True,
    )[: max(3, len(acts) // 3)]
    missing = [a for a in main if not a.resources]
    if not missing:
        return []
    detail = ", ".join(f"{a.activity_id}(dur={a.duration_days})" for a in missing[:8])
    return [
        _finding(
            rule,
            lang,
            evidence=f"missing_resources_on_main={detail}",
            description=(
                f"{len(missing)} high-duration activities lack resource assignments while other "
                f"activities in the same schedule have resources. Examples: {detail}."
            ),
            risk_score=55,
        )
    ]


def schedule_missing_handover(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    acts = ctx.activities()
    if len(acts) < 3:
        return []
    handover_re = re.compile(
        r"handover|taking.?over|provisional\s+acceptance|final\s+acceptance|substantial\s+completion|"
        r"practical\s+completion|Übergabe|Abnahme",
        re.I,
    )
    if any(handover_re.search(a.name) or handover_re.search(a.activity_id) for a in acts):
        return []
    return [
        _finding(
            rule,
            lang,
            evidence=f"activities_parsed={len(acts)}; handover_keywords=0",
            description=(
                f"Parsed {len(acts)} schedule activities but found no handover / taking-over / "
                f"provisional or final acceptance milestone near programme end."
            ),
            risk_score=50,
        )
    ]


# ----- BOQ -----


def boq_math_totals(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    errors = []
    for line in ctx.boq_lines():
        if line.qty is None or line.unit_price is None or line.total_price is None:
            continue
        expected = round(line.qty * line.unit_price, 2)
        actual = round(line.total_price, 2)
        if abs(expected - actual) > 0.05:
            errors.append(
                f"{line.code or '?'}: {line.qty}×{line.unit_price}={expected} but total={actual} "
                f"({line.document_name})"
            )
    if not errors:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(errors[:12]),
            description=f"{len(errors)} BOQ line(s) fail qty×rate=extension. {errors[0]}",
            risk_score=85,
        )
    ]


def boq_coding_scheme(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    lines = ctx.boq_lines()
    if not lines:
        return []
    gaeb_docs = [
        d
        for d in ctx.documents
        if d.subtype == "gaeb_lv" or (d.original_name or "").lower().endswith((".x83", ".x84", ".d83"))
    ]
    bad = []
    if gaeb_docs or ctx.country.upper() == "DE":
        # GAEB OZ: typically digits / dotted numeric
        for line in lines:
            code = (line.code or "").strip()
            if not code:
                continue
            if not re.fullmatch(r"\d{1,8}(?:\.\d{1,4})*", code):
                bad.append(f"{code} ({line.document_name})")
    elif ctx.country.upper() == "IR":
        for line in lines:
            code = (line.code or "").strip()
            if not code:
                continue
            # Fehrest-like: chapter-item patterns e.g. 07-01-001 or 0701001
            if not re.fullmatch(r"\d{2}[-.]?\d{2}[-.]?\d{2,4}|\d{5,10}", code):
                bad.append(f"{code} ({line.document_name})")
    else:
        return []
    if not bad:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence=f"invalid_codes={bad[:15]}",
            description=(
                f"{len(bad)} BOQ codes fail {('GAEB' if ctx.country.upper()=='DE' or gaeb_docs else 'Fehrest')} "
                f"pattern checks. Examples: {', '.join(bad[:8])}."
            ),
            risk_score=55,
        )
    ]


def boq_unit_mismatch(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    lines = [ln for ln in ctx.boq_lines() if ln.unit and ln.description]
    draw_text = ctx.text_blob(DocumentCategory.DRAWING) + "\n" + ctx.text_blob(DocumentCategory.TENDER)
    if not lines or not draw_text:
        return []
    mismatches = []
    # Same mark/name mentioned with a conflicting unit token nearby
    unit_aliases = {
        "m2": {"m2", "m²", "sqm", "sq.m", "square meter", "square metre"},
        "m3": {"m3", "m³", "cum", "cu.m", "cubic meter", "cubic metre"},
        "m": {"m", "lm", "ml", "meter", "metre"},
        "kg": {"kg", "kilogram"},
        "t": {"t", "ton", "tonne"},
        "pcs": {"pcs", "nr", "ea", "each", "st", "stück"},
    }

    def norm_unit(u: str) -> str:
        x = u.strip().lower().replace("²", "2").replace("³", "3")
        for canon, aliases in unit_aliases.items():
            if x in aliases or x == canon:
                return canon
        return x

    for line in lines[:200]:
        mark = None
        m = re.search(r"\b(Wall-[A-Z0-9]+|W-\d+|Slab-[A-Z0-9]+)\b", line.description, re.I)
        if m:
            mark = m.group(1)
        if not mark:
            continue
        boq_u = norm_unit(line.unit)
        # search mark in drawings/specs with unit in ±40 chars
        for dm in re.finditer(re.escape(mark), draw_text, re.I):
            window = draw_text[max(0, dm.start() - 40) : dm.end() + 40].lower()
            for canon, aliases in unit_aliases.items():
                if canon == boq_u:
                    continue
                if any(a in window for a in aliases):
                    mismatches.append(
                        f"BOQ {line.code} unit={line.unit} vs text near {mark} implying {canon}"
                    )
                    break
            if mismatches and mismatches[-1].startswith(f"BOQ {line.code} "):
                break
    # Dedupe: first conflict per BOQ code
    seen: set[str] = set()
    uniq: list[str] = []
    for m in mismatches:
        code = m.split()[1] if m.startswith("BOQ ") else m
        if code in seen:
            continue
        seen.add(code)
        uniq.append(m)
    mismatches = uniq
    if not mismatches:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(mismatches[:10]),
            description=f"{len(mismatches)} unit conflict(s) between BOQ and drawings/specs. {mismatches[0]}",
            risk_score=75,
        )
    ]


def boq_vs_drawing_presence(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    """Use Element Registry when available; else IFC marks vs BOQ text."""
    boq_text = " ".join(f"{ln.code} {ln.description}" for ln in ctx.boq_lines()).lower()
    if not boq_text:
        boq_text = ctx.text_blob(DocumentCategory.TENDER).lower()
    draw_docs = ctx.docs(DocumentCategory.DRAWING)
    if not draw_docs and not ctx.elements:
        return []

    missing_in_boq = []
    # Elements referenced by drawings/IFC but not BOQ
    for el in ctx.elements:
        mark = (el.type_mark or el.name_label or "").strip()
        if not mark:
            continue
        # only physical typed elements
        if el.element_type.lower() in {"project", "site", "building", "buildingstorey", "storey"}:
            continue
        draw_linked = any(
            d.id in el.document_ids
            for d in draw_docs
            if d.id is not None
        ) or any(
            (el.ifc_global_id or "")
            and (el.ifc_global_id in (d.extracted_text or "") or mark.lower() in (d.extracted_text or "").lower())
            for d in draw_docs
        )
        # Prefer elements that appear in IFC/drawing docs
        if not draw_linked and el.ifc_global_id:
            draw_linked = True
        if not draw_linked:
            continue
        if mark.lower() not in boq_text and (el.match_key or "").split(":")[-1] not in boq_text:
            missing_in_boq.append(f"{mark} (element_id={el.id}, ifc={el.ifc_global_id})")

    # Also: named IFC highlights in CDM
    if not missing_in_boq:
        for d in draw_docs:
            qty = d.canonical.get("quantities_summary") if isinstance(d.canonical.get("quantities_summary"), dict) else {}
            for h in qty.get("property_highlights") or []:
                if not isinstance(h, dict):
                    continue
                name = str(h.get("name") or "")
                if name and name.lower() not in boq_text:
                    missing_in_boq.append(f"{name} from {d.original_name}")

    if not missing_in_boq:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(missing_in_boq[:12]),
            description=(
                f"{len(missing_in_boq)} drawing/IFC object(s) have no matching BOQ reference. "
                f"Examples: {', '.join(missing_in_boq[:5])}."
            ),
            risk_score=80,
        )
    ]


# ----- Drawings / Tender -----


def drawing_revision_mismatch(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    draw_docs = ctx.docs(DocumentCategory.DRAWING)
    if len(draw_docs) < 2:
        return []
    rev_by_doc: dict[str, set[str]] = {}
    rev_re = re.compile(r"\brev(?:ision)?\s*[:\-]?\s*([A-Z0-9]{1,4})\b", re.I)
    for d in draw_docs:
        text = d.extracted_text or ""
        identity = d.canonical.get("identity") if isinstance(d.canonical.get("identity"), dict) else {}
        revs = set(rev_re.findall(text))
        if identity.get("revision"):
            revs.add(str(identity["revision"]))
        # discipline hint from name
        rev_by_doc[d.original_name] = {r.upper() for r in revs if r}

    nonempty = {k: v for k, v in rev_by_doc.items() if v}
    if len(nonempty) < 2:
        return []
    union = set.union(*nonempty.values())
    if len(union) <= 1:
        return []
    # conflict if docs disagree on primary revision
    primaries = {k: sorted(v)[-1] for k, v in nonempty.items()}
    if len(set(primaries.values())) <= 1:
        return []
    evidence = ", ".join(f"{k}→{v}" for k, v in primaries.items())
    return [
        _finding(
            rule,
            lang,
            evidence=evidence,
            description=f"Drawing revision identifiers disagree across sheets/disciplines: {evidence}.",
            risk_score=80,
        )
    ]


def itt_vs_schedule_deadlines(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    tender = ctx.text_blob(DocumentCategory.TENDER)
    sched = ctx.text_blob(DocumentCategory.SCHEDULE)
    if not tender or not sched:
        return []
    bid = extract_labeled_date(
        tender,
        ["bid deadline", "submission deadline", "closing date", "tender closing", "offer deadline"],
    )
    completion_t = extract_labeled_date(
        tender, ["completion date", "time for completion", "contract completion"]
    )
    completion_s = extract_labeled_date(
        sched, ["completion", "finish date", "project finish", "substantial completion"]
    )
    if completion_s is None:
        finishes = [a.finish for a in ctx.activities() if a.finish]
        if finishes:
            completion_s = max(finishes)
    issues = []
    if completion_t and completion_s and abs((completion_t - completion_s).days) > 1:
        issues.append(
            f"tender_completion={completion_t.isoformat()} schedule_completion={completion_s.isoformat()} "
            f"delta={abs((completion_t-completion_s).days)}d"
        )
    if bid and completion_s and bid > completion_s:
        issues.append(
            f"bid_deadline={bid.isoformat()} is after schedule_completion={completion_s.isoformat()}"
        )
    if not issues:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(issues),
            description="Deadline mismatch between tender documents and construction schedule: "
            + "; ".join(issues),
            risk_score=75,
        )
    ]


def itt_appendix_addenda_xrefs(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    tender_docs = ctx.docs(DocumentCategory.TENDER)
    if not tender_docs:
        return []
    text = "\n".join(d.extracted_text or "" for d in tender_docs)
    refs = set(
        m.group(1).lower()
        for m in re.finditer(
            r"\b(?:appendix|annex|addendum|anlage)\s*([A-Z]|\d{1,3})\b", text, re.I
        )
    )
    if not refs:
        return []
    names = " ".join(d.original_name.lower() for d in tender_docs)
    bodies = text.lower()
    missing = []
    for ref in sorted(refs):
        token = ref.lower()
        # presence: filename or dedicated heading
        present = (
            f"appendix {token}" in bodies
            or f"annex {token}" in bodies
            or f"addendum {token}" in bodies
            or f"appendix_{token}" in names
            or f"annex_{token}" in names
            or f"addendum_{token}" in names
            or f"addendum-{token}" in names
        )
        # referenced but only once as a pointer with no body section
        count = len(re.findall(rf"\b(?:appendix|annex|addendum)\s*{re.escape(ref)}\b", text, re.I))
        if count >= 1 and not present and f"appendix {token}" not in bodies:
            # weaker: if referenced >=2 times only as cross-ref without upload named
            if count >= 1 and token not in names:
                missing.append(ref)
    # Simpler deterministic rule: listed in "Appendices:" index but file not uploaded
    index_m = re.search(r"appendices?\s*:\s*([^\n]+)", text, re.I)
    if index_m:
        listed = re.findall(r"([A-Z]|\d{1,3})", index_m.group(1))
        for ref in listed:
            if ref.lower() not in names and f"appendix {ref.lower()}" not in bodies:
                missing.append(ref)
    missing = sorted(set(missing), key=str)
    if not missing:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence=f"unresolved_xrefs={missing}",
            description=(
                f"Tender pack references appendix/annex/addendum {missing} but corresponding "
                f"uploaded sections/files were not resolved."
            ),
            risk_score=50,
        )
    ]


# ----- Standards -----


def standard_version_is_current(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    stale = []
    for s in ctx.selected_standards:
        code = str(s.get("code") or "")
        meta = ctx.standard_versions.get(code) or {}
        # allow flags on selected_standards themselves
        is_current = s.get("is_current", meta.get("is_current"))
        if is_current is False or str(s.get("status") or meta.get("status") or "").lower() in {
            "superseded",
            "withdrawn",
        }:
            newer = s.get("newer_version") or meta.get("newer_version") or "unknown"
            stale.append(f"{code} (newer={newer})")
    if not stale:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(stale),
            description=f"Project bound to superseded StandardVersion(s): {', '.join(stale)}.",
            risk_score=80,
        )
    ]


def mandatory_standard_completeness(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    try:
        country = CountryCode(ctx.country)
    except ValueError:
        return []
    selected = {str(s.get("code")) for s in ctx.selected_standards if s.get("is_selected", True)}
    missing = []
    for std in list_standards_for_country(country):
        level = applicability_level(std, country, ctx.project_type)
        if level != "mandatory_default":
            continue
        if std.code not in selected:
            # also accept uploaded standard document named with code
            uploaded = any(
                std.code.lower() in (d.original_name or "").lower()
                or std.code.lower() in (d.extracted_text or "")[:500].lower()
                for d in ctx.docs(DocumentCategory.STANDARD)
            )
            if not uploaded:
                missing.append(std.code)
    if not missing:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence=f"missing_mandatory={missing[:20]}; selected_count={len(selected)}",
            description=(
                f"{len(missing)} mandatory standard(s) for {country.value}/{ctx.project_type.value} "
                f"are not selected/uploaded. Examples: {', '.join(missing[:8])}."
            ),
            risk_score=80,
        )
    ]


def standard_extraction_confidence(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    from app.services.extractor import (
        EXTRACTION_CONFIDENCE_LIMITATION_THRESHOLD,
        get_extraction_confidence,
        has_low_extraction_confidence,
    )

    low = []
    for d in ctx.docs(DocumentCategory.STANDARD):
        # Same helper as documents_with_limitations / analyzer stats.
        if not has_low_extraction_confidence(d):
            continue
        conf = get_extraction_confidence(d)
        low.append(f"{d.original_name} confidence={conf}")
    if not low:
        return []
    thr = int(EXTRACTION_CONFIDENCE_LIMITATION_THRESHOLD)
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(low),
            description=(
                f"{len(low)} uploaded standard(s) have extraction confidence below {thr}. {low[0]}."
            ),
            risk_score=50,
            recommendation="Re-upload a searchable PDF or improve OCR before relying on clause checks.",
        )
    ]


# ----- Geotech / ER / Addenda -----


_GEOTECH_TYPES = {
    ProjectType.BRIDGE,
    ProjectType.TUNNEL,
    ProjectType.DAM_WATER,
    ProjectType.INFRASTRUCTURE,
    ProjectType.ROAD_HIGHWAY,
    ProjectType.RAILWAY,
    ProjectType.PORT_MARINE,
    ProjectType.AIRPORT,
}


def geotech_report_required(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    if ctx.project_type not in _GEOTECH_TYPES and ctx.project_type not in {
        ProjectType.OFFICE,
        ProjectType.RESIDENTIAL,
        ProjectType.HOSPITAL,
        ProjectType.INDUSTRIAL,
    }:
        # still require for major building + civil
        pass
    # Require for civil always; for building types listed above also
    needs = ctx.project_type in _GEOTECH_TYPES or ctx.project_type in {
        ProjectType.OFFICE,
        ProjectType.RESIDENTIAL,
        ProjectType.HOSPITAL,
        ProjectType.INDUSTRIAL,
        ProjectType.DATA_CENTER,
    }
    if not needs:
        return []
    geotech_re = re.compile(r"geotech|geotechnical|soil\s+report|borehole|site\s+investigation", re.I)
    present = False
    for d in ctx.documents:
        name = d.original_name or ""
        sub = d.subtype or ""
        if geotech_re.search(name) or "geotech" in sub.lower():
            present = True
            break
        if geotech_re.search((d.extracted_text or "")[:2000]):
            # only count if substantial geotech content, not a mere mention
            if len(re.findall(geotech_re, d.extracted_text or "")) >= 3:
                present = True
                break
    if present:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence=(
                f"project_type={ctx.project_type.value}; documents={len(ctx.documents)}; "
                f"geotech_upload=false"
            ),
            description=(
                f"Project type '{ctx.project_type.value}' typically requires a Geotechnical Report, "
                f"but none was identified among {len(ctx.documents)} uploaded document(s)."
            ),
            risk_score=80,
        )
    ]


def geotech_report_staleness(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    threshold = 730  # days (~2 years) default
    geo_docs = []
    geo_re = re.compile(r"geotech|geotechnical|soil\s+report", re.I)
    for d in ctx.documents:
        if geo_re.search(d.original_name or "") or geo_re.search((d.extracted_text or "")[:1500]):
            geo_docs.append(d)
    if not geo_docs:
        return []
    project_start = ctx.project_start
    if project_start is None:
        project_start = extract_labeled_date(
            ctx.text_blob(DocumentCategory.TENDER, DocumentCategory.SCHEDULE),
            ["project start", "commencement", "ntp", "programme start"],
        ) or date.today()
    stale = []
    for d in geo_docs:
        report_date = extract_labeled_date(
            d.extracted_text or "",
            ["report date", "dated", "investigation date", "date"],
        )
        if report_date is None:
            dates = extract_dates(d.extracted_text or "")
            report_date = dates[0] if dates else None
        if report_date is None:
            continue
        age = (project_start - report_date).days
        if age > threshold:
            stale.append(
                f"{d.original_name}: report_date={report_date.isoformat()} "
                f"project_start={project_start.isoformat()} age_days={age}"
            )
    if not stale:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(stale),
            description=(
                f"Geotechnical report age exceeds {threshold} days vs project start. {stale[0]}."
            ),
            risk_score=55,
        )
    ]


def er_vs_boq_drawing_presence(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    er_docs = [
        d
        for d in ctx.docs(DocumentCategory.TENDER)
        if re.search(r"employer\s+req|ER\b|requirements", d.original_name, re.I)
        or "employer requirement" in (d.extracted_text or "").lower()[:800]
        or d.subtype in {"employer_requirements", "er"}
    ]
    if not er_docs:
        return []
    boq = " ".join(f"{x.code} {x.description}" for x in ctx.boq_lines()).lower()
    draw = ctx.text_blob(DocumentCategory.DRAWING).lower()
    corpus = boq + "\n" + draw
    missing = []
    req_re = re.compile(
        r"(?:shall\s+provide|must\s+include|requirement\s*\d*\s*[:\-])\s+([^\n.]{8,80})",
        re.I,
    )
    for d in er_docs:
        for m in req_re.finditer(d.extracted_text or ""):
            phrase = m.group(1).strip()
            # key tokens (nouns-ish): take significant words
            tokens = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", phrase) if t.lower() not in {
                "shall", "must", "with", "that", "this", "from", "into", "provide", "include"
            }]
            if not tokens:
                continue
            if not any(t.lower() in corpus for t in tokens[:3]):
                missing.append(phrase[:120])
    if not missing:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(missing[:10]),
            description=(
                f"{len(missing)} Employer Requirement statement(s) lack a matching BOQ item or drawing "
                f"reference. Example: {missing[0]}"
            ),
            risk_score=80,
        )
    ]


def addendum_after_deadline(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    tender = ctx.text_blob(DocumentCategory.TENDER)
    deadline = extract_labeled_date(
        tender,
        ["bid deadline", "submission deadline", "closing date", "tender closing"],
    )
    if not deadline:
        return []
    issues = []
    add_re = re.compile(r"addendum|addenda", re.I)
    for d in ctx.docs(DocumentCategory.TENDER):
        if not (add_re.search(d.original_name or "") or add_re.search((d.extracted_text or "")[:500])):
            continue
        issued = extract_labeled_date(
            d.extracted_text or "",
            ["issue date", "issued", "addendum date", "date"],
        )
        if issued is None:
            dates = extract_dates(d.extracted_text or "")
            issued = dates[0] if dates else None
        if issued and issued > deadline:
            ext = extract_labeled_date(
                tender + "\n" + (d.extracted_text or ""),
                ["extended deadline", "new closing", "deadline extension", "revised closing"],
            )
            if ext and ext >= issued:
                continue
            issues.append(
                f"{d.original_name}: issued={issued.isoformat()} deadline={deadline.isoformat()}"
            )
    if not issues:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(issues),
            description=(
                f"Addendum issued after bid deadline without a recorded extension. {issues[0]}."
            ),
            risk_score=80,
        )
    ]


def addendum_orphaned(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    addenda = [
        d
        for d in ctx.docs(DocumentCategory.TENDER)
        if re.search(r"addendum|addenda", d.original_name, re.I)
        or re.search(r"\baddendum\b", (d.extracted_text or "")[:400], re.I)
    ]
    if not addenda:
        return []
    boq = " ".join(f"{x.code} {x.description}" for x in ctx.boq_lines()).lower()
    draw = ctx.text_blob(DocumentCategory.DRAWING).lower()
    orphans = []
    change_re = re.compile(
        r"(?:replace|revise|add|delete|change)\s+([A-Za-z0-9][A-Za-z0-9\-/ ]{2,40})",
        re.I,
    )
    for d in addenda:
        for m in change_re.finditer(d.extracted_text or ""):
            target = m.group(1).strip().lower()
            token = re.findall(r"[a-z0-9\-]{3,}", target)
            if not token:
                continue
            key = token[0]
            if key not in boq and key not in draw:
                orphans.append(f"{d.original_name}: '{m.group(0)[:80]}'")
    if not orphans:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence="; ".join(orphans[:10]),
            description=(
                f"{len(orphans)} addendum change(s) not reflected in BOQ/drawings. Example: {orphans[0]}"
            ),
            risk_score=75,
        )
    ]


def addendum_sequence_gap(rule: RuleDef, ctx: RuleContext, lang: LanguageCode) -> list[RiskFinding]:
    nums = set()
    for d in ctx.documents:
        for m in re.finditer(r"addendum\s*(?:no\.?\s*)?(\d{1,3})\b", d.original_name or "", re.I):
            nums.add(int(m.group(1)))
        for m in re.finditer(r"addendum\s*(?:no\.?\s*)?(\d{1,3})\b", (d.extracted_text or "")[:800], re.I):
            nums.add(int(m.group(1)))
    if len(nums) < 2:
        return []
    lo, hi = min(nums), max(nums)
    missing = [n for n in range(lo, hi + 1) if n not in nums]
    if not missing:
        return []
    return [
        _finding(
            rule,
            lang,
            evidence=f"present={sorted(nums)}; missing={missing}",
            description=(
                f"Addenda sequence gap: present {sorted(nums)}, missing {missing}."
            ),
            risk_score=55,
        )
    ]


CHECK_RUNNERS: dict[str, Runner] = {
    "schedule_orphan_activity": schedule_orphan_activity,
    "schedule_invalid_duration": schedule_invalid_duration,
    "schedule_end_before_start": schedule_end_before_start,
    "schedule_negative_float": schedule_negative_float,
    "schedule_vs_contract_ntp": schedule_vs_contract_ntp,
    "schedule_missing_resources": schedule_missing_resources,
    "schedule_missing_handover": schedule_missing_handover,
    "boq_unit_mismatch": boq_unit_mismatch,
    "boq_vs_drawing_presence": boq_vs_drawing_presence,
    "boq_math_totals": boq_math_totals,
    "boq_coding_scheme": boq_coding_scheme,
    "drawing_revision_mismatch": drawing_revision_mismatch,
    "itt_vs_schedule_deadlines": itt_vs_schedule_deadlines,
    "itt_appendix_addenda_xrefs": itt_appendix_addenda_xrefs,
    "standard_version_is_current": standard_version_is_current,
    "mandatory_standard_completeness": mandatory_standard_completeness,
    "standard_extraction_confidence": standard_extraction_confidence,
    "geotech_report_required": geotech_report_required,
    "geotech_report_staleness": geotech_report_staleness,
    "er_vs_boq_drawing_presence": er_vs_boq_drawing_presence,
    "addendum_after_deadline": addendum_after_deadline,
    "addendum_orphaned": addendum_orphaned,
    "addendum_sequence_gap": addendum_sequence_gap,
}
