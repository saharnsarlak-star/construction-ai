"""Python-first discrepancy detectors for [HYBRID] seed rules (Phase 4).

These NEVER call an LLM. AI layer only explains returned discrepancies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models import DocumentCategory
from app.services.rule_engine.context import RuleContext, extract_labeled_date


@dataclass
class HybridDiscrepancy:
    check: str
    summary: str
    evidence: str
    excerpts: list[dict[str, str]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def detect_hybrid_discrepancy(check: str, ctx: RuleContext) -> HybridDiscrepancy | None:
    fn = _DETECTORS.get(check)
    if not fn:
        return None
    return fn(ctx)


def _schedule_cp_outlier(ctx: RuleContext) -> HybridDiscrepancy | None:
    acts = [a for a in ctx.activities() if a.duration_days and a.duration_days > 0]
    if len(acts) < 3:
        return None
    total = sum(a.duration_days or 0 for a in acts)
    longest = max(acts, key=lambda a: a.duration_days or 0)
    share = (longest.duration_days or 0) / total if total else 0
    # Outlier: one activity > 60% of summed durations or critical path span absurd
    starts = [a.start for a in acts if a.start]
    finishes = [a.finish for a in acts if a.finish]
    span = None
    if starts and finishes:
        span = (max(finishes) - min(starts)).days
    if share < 0.6 and not (span and span > 0 and total > span * 2.5):
        return None
    return HybridDiscrepancy(
        check="schedule_cp_outlier",
        summary=(
            f"Activity {longest.activity_id} duration={longest.duration_days}d is "
            f"{share:.0%} of summed activity durations ({total}d)"
            + (f"; programme span={span}d" if span is not None else "")
        ),
        evidence=f"longest={longest.activity_id}; duration={longest.duration_days}; share={share:.3f}; total={total}",
        excerpts=[{"document": longest.document_name, "text": longest.source_line}],
        metrics={"longest_id": longest.activity_id, "share": share, "total_duration": total, "span_days": span},
    )


def _schedule_lag_lead(ctx: RuleContext) -> HybridDiscrepancy | None:
    text = ctx.text_blob(DocumentCategory.SCHEDULE)
    acts = ctx.activities()
    if not acts:
        return None
    # Relationships present but lag/lead never specified
    linked = [a for a in acts if a.predecessors]
    if len(linked) < 2:
        return None
    if re.search(r"\b(?:lag|lead)\s*[:=]\s*-?\d+", text, re.I):
        return None
    return HybridDiscrepancy(
        check="schedule_lag_lead",
        summary=f"{len(linked)} predecessor links found but no lag/lead values in schedule export.",
        evidence=f"linked_activities={len(linked)}; lag_lead_tokens=0",
        excerpts=[{"document": linked[0].document_name, "text": linked[0].source_line}],
        metrics={"linked": len(linked)},
    )


def _schedule_overlap_duplicate(ctx: RuleContext) -> HybridDiscrepancy | None:
    acts = [a for a in ctx.activities() if a.start and a.finish]
    issues = []
    by_name: dict[str, list] = {}
    for a in acts:
        key = re.sub(r"\s+", " ", (a.name or "").strip().lower())
        by_name.setdefault(key, []).append(a)
    for name, group in by_name.items():
        if name and len(group) > 1:
            issues.append(f"duplicate name '{group[0].name}': {[g.activity_id for g in group]}")
    for i, a in enumerate(acts):
        for b in acts[i + 1 :]:
            if a.activity_id == b.activity_id:
                continue
            if a.start <= b.finish and b.start <= a.finish:
                # same resource pool hint
                if set(a.resources) & set(b.resources) and a.resources:
                    issues.append(
                        f"overlap {a.activity_id}/{b.activity_id} shared resources={sorted(set(a.resources)&set(b.resources))}"
                    )
    if not issues:
        return None
    return HybridDiscrepancy(
        check="schedule_overlap_duplicate",
        summary=f"{len(issues)} duplicate/overlap issue(s) detected.",
        evidence="; ".join(issues[:8]),
        excerpts=[{"document": acts[0].document_name, "text": issues[0]}],
        metrics={"issue_count": len(issues)},
    )


def _contract_vs_itt_deadlines(ctx: RuleContext) -> HybridDiscrepancy | None:
    tender_docs = ctx.docs(DocumentCategory.TENDER)
    if len(tender_docs) < 1:
        return None
    # Split contract-like vs ITT-like by filename/keywords
    contract_text = ""
    itt_text = ""
    for d in tender_docs:
        name = (d.original_name or "").lower()
        body = d.extracted_text or ""
        if any(k in name for k in ("contract", "agreement", "conditions")) or "notice to proceed" in body.lower():
            contract_text += "\n" + body
        if any(k in name for k in ("itt", "invitation", "tender", "instruction")) or "bid deadline" in body.lower():
            itt_text += "\n" + body
    if not contract_text:
        contract_text = ctx.text_blob(DocumentCategory.TENDER)
    if not itt_text:
        itt_text = contract_text
    c_comp = extract_labeled_date(contract_text, ["completion date", "time for completion", "contract completion"])
    i_comp = extract_labeled_date(itt_text, ["completion date", "time for completion", "tender completion"])
    c_start = extract_labeled_date(contract_text, ["commencement", "ntp", "notice to proceed", "start date"])
    i_start = extract_labeled_date(itt_text, ["commencement", "start date", "programme start"])
    diffs = []
    if c_comp and i_comp and abs((c_comp - i_comp).days) > 1:
        diffs.append(f"completion contract={c_comp.isoformat()} itt={i_comp.isoformat()} delta={(c_comp-i_comp).days}d")
    if c_start and i_start and abs((c_start - i_start).days) > 1:
        diffs.append(f"start contract={c_start.isoformat()} itt={i_start.isoformat()} delta={(c_start-i_start).days}d")
    if not diffs:
        return None
    return HybridDiscrepancy(
        check="contract_vs_itt_deadlines",
        summary="Contract vs Tender deadline mismatch: " + "; ".join(diffs),
        evidence="; ".join(diffs),
        excerpts=[
            {"document": "contract", "text": f"completion={c_comp} start={c_start}"},
            {"document": "itt", "text": f"completion={i_comp} start={i_start}"},
        ],
        metrics={"diffs": diffs},
    )


def _contract_vs_boq_scope(ctx: RuleContext) -> HybridDiscrepancy | None:
    contract = ctx.text_blob(DocumentCategory.TENDER)
    lines = ctx.boq_lines()
    if not lines or not contract:
        return None
    m = re.search(
        r"(?:total\s+(?:gross\s+)?floor\s+area|GFA|built-?up area|work volume)\s*[:\-]?\s*([\d.,]+)\s*(m2|m²|sqm)?",
        contract,
        re.I,
    )
    if not m:
        return None
    stated = float(m.group(1).replace(",", ""))
    # sum BOQ m2 items
    boq_m2 = sum((ln.qty or 0) for ln in lines if (ln.unit or "").lower() in {"m2", "m²", "sqm"})
    if boq_m2 <= 0:
        return None
    ratio = boq_m2 / stated if stated else 0
    if 0.5 <= ratio <= 2.0:
        return None
    return HybridDiscrepancy(
        check="contract_vs_boq_scope",
        summary=f"Contract stated area/volume={stated} vs BOQ m2 sum={boq_m2:.1f} (ratio={ratio:.2f})",
        evidence=f"stated={stated}; boq_m2_sum={boq_m2}; ratio={ratio:.3f}",
        excerpts=[{"document": "contract", "text": m.group(0)}, {"document": "boq", "text": f"m2_sum={boq_m2}"}],
        metrics={"stated": stated, "boq_m2": boq_m2, "ratio": ratio},
    )


def _specs_standards_vs_project_type(ctx: RuleContext) -> HybridDiscrepancy | None:
    text = ctx.text_blob(DocumentCategory.TENDER, DocumentCategory.STANDARD)
    citations = sorted(set(re.findall(r"\b(?:DIN|EN|ISO|ASTM|ACI|BS)\s*[\w.\-/]+\b", text, re.I)))
    if not citations:
        return None
    ptype = ctx.project_type.value
    # Crude mismatch: highway standards on office, or medical on bridge
    mismatches = []
    joined = " ".join(citations).upper()
    if ptype in {"office", "residential"} and re.search(r"AASHTO|HIGHWAY|RAIL", joined):
        mismatches.append("transportation standards cited on building project")
    if ptype in {"bridge", "road_highway"} and re.search(r"ASHRAE|HVAC|NBC.?FIRE", joined):
        mismatches.append("building-services standards cited on civil project")
    if not mismatches:
        # still pass citations to AI if project type civil and only building DIN 4108 energy etc. — skip if none
        return None
    return HybridDiscrepancy(
        check="specs_standards_vs_project_type",
        summary=f"Possible standard/project-type mismatch ({ptype}): {'; '.join(mismatches)}. Citations: {citations[:8]}",
        evidence=f"project_type={ptype}; citations={citations[:15]}; issues={mismatches}",
        excerpts=[{"document": "specs", "text": ", ".join(citations[:8])}],
        metrics={"citations": citations, "project_type": ptype},
    )


def _specs_vs_drawings(ctx: RuleContext) -> HybridDiscrepancy | None:
    spec = ctx.text_blob(DocumentCategory.TENDER)
    draw = ctx.text_blob(DocumentCategory.DRAWING)
    if not spec or not draw:
        return None
    issues = []
    # fire rating conflict example
    spec_fire = re.findall(r"(?:REI|F|fire\s*rating)\s*[:\-]?\s*(\d{2,3})", spec, re.I)
    draw_fire = re.findall(r"(?:REI|F|fire\s*rating)\s*[:\-]?\s*(\d{2,3})", draw, re.I)
    if spec_fire and draw_fire and set(spec_fire) != set(draw_fire):
        issues.append(f"fire_rating spec={spec_fire[:3]} drawing={draw_fire[:3]}")
    # concrete grade
    spec_c = re.findall(r"\bC\s?(\d{2}/\d{2})\b", spec)
    draw_c = re.findall(r"\bC\s?(\d{2}/\d{2})\b", draw)
    if spec_c and draw_c and set(spec_c) != set(draw_c):
        issues.append(f"concrete_grade spec={spec_c[:3]} drawing={draw_c[:3]}")
    if not issues:
        return None
    return HybridDiscrepancy(
        check="specs_vs_drawings",
        summary="Specification vs drawing numeric conflicts: " + "; ".join(issues),
        evidence="; ".join(issues),
        excerpts=[{"document": "spec/drawing", "text": issues[0]}],
        metrics={"issues": issues},
    )


def _boq_qty_vs_area(ctx: RuleContext) -> HybridDiscrepancy | None:
    lines = ctx.boq_lines()
    if not lines:
        return None
    # Outlier: single item qty huge vs others
    qtys = [(ln, ln.qty) for ln in lines if ln.qty and ln.qty > 0]
    if len(qtys) < 2:
        return None
    vals = [q for _, q in qtys]
    avg = sum(vals) / len(vals)
    outliers = [ln for ln, q in qtys if q > max(avg * 20, avg + 5000)]
    if not outliers:
        return None
    o = outliers[0]
    return HybridDiscrepancy(
        check="boq_qty_vs_area",
        summary=f"BOQ item {o.code} qty={o.qty} is an outlier vs mean={avg:.1f}",
        evidence=f"code={o.code}; qty={o.qty}; mean={avg:.2f}; unit={o.unit}",
        excerpts=[{"document": o.document_name, "text": f"{o.code} {o.description} qty={o.qty} {o.unit}"}],
        metrics={"code": o.code, "qty": o.qty, "mean": avg},
    )


def _drawing_scale_vs_dimensions(ctx: RuleContext) -> HybridDiscrepancy | None:
    text = ctx.text_blob(DocumentCategory.DRAWING)
    if not text:
        return None
    scale = re.search(r"scale\s*[:=]?\s*1\s*:\s*(\d+)", text, re.I)
    # stated length with measured annotation conflict heuristic: "length 12.0m" vs scale bar
    if not scale:
        return None
    s = int(scale.group(1))
    # Flag unusual scales for plans
    if s in {50, 100, 200, 500}:
        return None
    return HybridDiscrepancy(
        check="drawing_scale_vs_dimensions",
        summary=f"Unusual stated scale 1:{s} on drawing set — verify against annotated dimensions.",
        evidence=f"scale=1:{s}",
        excerpts=[{"document": "drawing", "text": scale.group(0)}],
        metrics={"scale": s},
    )


def _standard_clause_semantic_compliance(ctx: RuleContext) -> HybridDiscrepancy | None:
    if not ctx.selected_standards:
        return None
    # Python retrieves that standards are selected; AI checks semantic compliance
    codes = [str(s.get("code")) for s in ctx.selected_standards if s.get("is_selected", True)]
    if not codes:
        return None
    tender = ctx.text_blob(DocumentCategory.TENDER, DocumentCategory.STANDARD)
    missing = [c for c in codes if c.lower() not in tender.lower()]
    # Always a soft discrepancy if tender never cites the mandatory codes
    if not missing:
        return None
    return HybridDiscrepancy(
        check="standard_clause_semantic_compliance",
        summary=f"Selected standards not cited in tender text: {missing[:8]}",
        evidence=f"selected={codes[:10]}; uncited={missing[:10]}",
        excerpts=[{"document": "standards", "text": ", ".join(missing[:8])}],
        metrics={"uncited": missing},
    )


def _standard_framework_conflict(ctx: RuleContext) -> HybridDiscrepancy | None:
    codes = [str(s.get("code") or "") for s in ctx.selected_standards]
    text = " ".join(codes).upper() + "\n" + ctx.text_blob(DocumentCategory.TENDER).upper()
    has_vob = "VOB" in text or "DE_VOB" in text
    has_fidic = "FIDIC" in text
    has_ccdc = "CCDC" in text
    frameworks = sum([has_vob, has_fidic, has_ccdc])
    if frameworks < 2:
        return None
    return HybridDiscrepancy(
        check="standard_framework_conflict",
        summary=f"Multiple contract frameworks detected (VOB={has_vob}, FIDIC={has_fidic}, CCDC={has_ccdc})",
        evidence=f"VOB={has_vob}; FIDIC={has_fidic}; CCDC={has_ccdc}",
        excerpts=[{"document": "tender/standards", "text": text[:240]}],
        metrics={"vob": has_vob, "fidic": has_fidic, "ccdc": has_ccdc},
    )


def _geotech_vs_foundation_drawings(ctx: RuleContext) -> HybridDiscrepancy | None:
    geo = ""
    for d in ctx.documents:
        if re.search(r"geotech|soil", d.original_name, re.I) or "bearing" in (d.extracted_text or "").lower():
            geo += "\n" + (d.extracted_text or "")
    draw = ctx.text_blob(DocumentCategory.DRAWING)
    if not geo or not draw:
        return None
    g = re.search(r"bearing\s+capacity\s*[:\-]?\s*([\d.]+)\s*(kPa|kN/?m2)?", geo, re.I)
    d = re.search(r"bearing\s+capacity\s*[:\-]?\s*([\d.]+)\s*(kPa|kN/?m2)?", draw, re.I)
    if not g:
        return None
    gval = float(g.group(1))
    if d:
        dval = float(d.group(1))
        if abs(gval - dval) / max(gval, 1) < 0.15:
            return None
        return HybridDiscrepancy(
            check="geotech_vs_foundation_drawings",
            summary=f"Bearing capacity geotech={gval} vs drawing={dval}",
            evidence=f"geotech={g.group(0)}; drawing={d.group(0)}",
            excerpts=[{"document": "geotech", "text": g.group(0)}, {"document": "drawing", "text": d.group(0)}],
            metrics={"geotech": gval, "drawing": dval},
        )
    # foundation drawing present without matching capacity
    if re.search(r"foundation|footing|pile", draw, re.I):
        return HybridDiscrepancy(
            check="geotech_vs_foundation_drawings",
            summary=f"Geotech bearing capacity {gval} stated but foundation drawings do not restate/confirm it.",
            evidence=g.group(0),
            excerpts=[{"document": "geotech", "text": g.group(0)}],
            metrics={"geotech": gval},
        )
    return None


def _geotech_borehole_density(ctx: RuleContext) -> HybridDiscrepancy | None:
    text = ""
    for d in ctx.documents:
        if re.search(r"geotech|soil|borehole", d.original_name, re.I) or "borehole" in (d.extracted_text or "").lower():
            text += "\n" + (d.extracted_text or "")
    if not text:
        return None
    holes = len(re.findall(r"\b(?:BH|borehole)\s*-?\s*\d+", text, re.I))
    area_m = re.search(r"(?:site|footprint)\s*area\s*[:\-]?\s*([\d.,]+)\s*m2", text, re.I)
    if not area_m:
        area_m = re.search(r"GFA\s*[:\-]?\s*([\d.,]+)", text, re.I)
    if holes == 0:
        return None
    area = float(area_m.group(1).replace(",", "")) if area_m else None
    # Rule of thumb: <1 borehole per 1000 m2 for large sites
    if area and area > 2000 and holes < max(2, int(area / 1000)):
        return HybridDiscrepancy(
            check="geotech_borehole_density",
            summary=f"Only {holes} borehole(s) for site area ~{area} m2",
            evidence=f"boreholes={holes}; area_m2={area}",
            excerpts=[{"document": "geotech", "text": f"boreholes={holes}, area={area}"}],
            metrics={"boreholes": holes, "area": area},
        )
    if holes == 1 and (area or 0) > 1500:
        return HybridDiscrepancy(
            check="geotech_borehole_density",
            summary=f"Single borehole for large site (area={area})",
            evidence=f"boreholes=1; area={area}",
            excerpts=[{"document": "geotech", "text": "BH-01"}],
            metrics={"boreholes": 1, "area": area},
        )
    return None


def _er_vs_technical_specs(ctx: RuleContext) -> HybridDiscrepancy | None:
    er = ""
    spec = ""
    for d in ctx.docs(DocumentCategory.TENDER):
        name = (d.original_name or "").lower()
        body = d.extracted_text or ""
        if "employer" in name or "requirement" in name or "employer requirement" in body.lower()[:500]:
            er += "\n" + body
        if "spec" in name or "specification" in body.lower()[:400]:
            spec += "\n" + body
    if not er or not spec:
        return None
    # opposing thermal U-value example
    er_u = re.findall(r"U\s*[- ]?value\s*[:≤<]\s*([\d.]+)", er, re.I)
    sp_u = re.findall(r"U\s*[- ]?value\s*[:≤<]\s*([\d.]+)", spec, re.I)
    if er_u and sp_u and er_u[0] != sp_u[0]:
        return HybridDiscrepancy(
            check="er_vs_technical_specs",
            summary=f"ER U-value={er_u[0]} vs Spec U-value={sp_u[0]}",
            evidence=f"er={er_u[0]}; spec={sp_u[0]}",
            excerpts=[{"document": "ER", "text": f"U-value {er_u[0]}"}, {"document": "spec", "text": f"U-value {sp_u[0]}"}],
            metrics={"er_u": er_u[0], "spec_u": sp_u[0]},
        )
    return None


def _er_vs_standard_clause(ctx: RuleContext) -> HybridDiscrepancy | None:
    er = ""
    for d in ctx.docs(DocumentCategory.TENDER):
        if re.search(r"employer|requirement", d.original_name, re.I):
            er += "\n" + (d.extracted_text or "")
    if not er:
        return None
    # Detect "may omit fire protection" vs mandatory fire standard selected
    if re.search(r"may\s+omit\s+fire|fire\s+protection\s+not\s+required", er, re.I):
        codes = [str(s.get("code")) for s in ctx.selected_standards]
        if any("FIRE" in c.upper() or "4102" in c or "BRAND" in c.upper() for c in codes) or True:
            return HybridDiscrepancy(
                check="er_vs_standard_clause",
                summary="ER language appears to relax fire protection while fire standards typically apply.",
                evidence="ER contains 'may omit fire' / similar + selected_standards=" + str(codes[:6]),
                excerpts=[{"document": "ER", "text": "may omit fire protection"}],
                metrics={"codes": codes},
            )
    return None


_DETECTORS = {
    "schedule_cp_outlier": _schedule_cp_outlier,
    "schedule_lag_lead": _schedule_lag_lead,
    "schedule_overlap_duplicate": _schedule_overlap_duplicate,
    "contract_vs_itt_deadlines": _contract_vs_itt_deadlines,
    "contract_vs_boq_scope": _contract_vs_boq_scope,
    "specs_standards_vs_project_type": _specs_standards_vs_project_type,
    "specs_vs_drawings": _specs_vs_drawings,
    "boq_qty_vs_area": _boq_qty_vs_area,
    "drawing_scale_vs_dimensions": _drawing_scale_vs_dimensions,
    "standard_clause_semantic_compliance": _standard_clause_semantic_compliance,
    "standard_framework_conflict": _standard_framework_conflict,
    "geotech_vs_foundation_drawings": _geotech_vs_foundation_drawings,
    "geotech_borehole_density": _geotech_borehole_density,
    "er_vs_technical_specs": _er_vs_technical_specs,
    "er_vs_standard_clause": _er_vs_standard_clause,
}
