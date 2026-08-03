"""Orchestrate [PYTHON] seed rule runners behind NEW_RULE_ENGINE_ENABLED."""

from __future__ import annotations

import logging
from typing import Any

from app.knowledge.seed_rules_batch1 import build_seed_batch1_rules
from app.knowledge.seed_rules_batch2 import build_seed_batch2_rules
from app.knowledge.rules_registry import RuleDef
from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType
from app.services.analyzer import RiskFinding
from app.services.rule_engine.context import (
    ElementView,
    RuleContext,
    build_doc_view,
)
from app.services.rule_engine.runners import CHECK_RUNNERS

logger = logging.getLogger(__name__)


def list_python_seed_rules() -> list[RuleDef]:
    rules = build_seed_batch1_rules() + build_seed_batch2_rules()
    return [r for r in rules if (r.logic_config or {}).get("ownership_tag") == "PYTHON"]


def run_python_seed_rules(
    *,
    country: CountryCode | str,
    report_language: LanguageCode,
    documents: list[dict[str, Any]],
    project_type: ProjectType | str | None = None,
    selected_standards: list[dict[str, Any]] | None = None,
    elements: list[dict[str, Any]] | list[ElementView] | None = None,
    project_id: int | None = None,
    project_start: Any = None,
    standard_versions: dict[str, dict[str, Any]] | None = None,
    rkb_catalog: dict[str, dict[str, Any]] | None = None,
) -> list[RiskFinding]:
    """
    Execute all [PYTHON] seed checks. Returns RiskFinding list with source_layer=rule_based.
    Does not call or modify the keyword analyzer.
    When rkb_catalog is provided (Phase 6 DB snapshot), risk_id mapping uses it;
    otherwise falls back to Python seed dicts.
    """
    from app.config import settings
    from app.knowledge.rkb import python_risk_catalog
    from app.services.rule_engine.runners import set_rkb_catalog

    if rkb_catalog is not None:
        set_rkb_catalog(rkb_catalog)
    elif settings.rkb_db_enabled:
        # Flag on but no snapshot passed — still use Python until caller supplies DB catalog
        set_rkb_catalog(python_risk_catalog())
    else:
        set_rkb_catalog(None)

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
        country=country.value if isinstance(country, CountryCode) else str(country),
        project_type=ptype,
        documents=[build_doc_view(d) for d in documents],
        selected_standards=selected_standards or [],
        elements=element_views,
        project_start=project_start,
        standard_versions=standard_versions or {},
    )

    findings: list[RiskFinding] = []
    try:
        for rule in list_python_seed_rules():
            # Engine-6 gate: if the pattern's base document category is absent,
            # skip the pattern entirely. Completeness findings (SCHED-001 etc.)
            # are emitted once by the keyword/completeness layer — never here.
            req = rule.requires_category
            if req is not None and not ctx.docs(req):
                # STANDARD patterns may still run when catalog standards were
                # selected even without an uploaded STANDARD file.
                if not (
                    req == DocumentCategory.STANDARD and ctx.selected_standards
                ):
                    logger.debug(
                        "Skip %s: required category %s absent",
                        rule.code,
                        req.value if hasattr(req, "value") else req,
                    )
                    continue
            check = str((rule.logic_config or {}).get("check") or "")
            runner = CHECK_RUNNERS.get(check)
            if runner is None:
                logger.warning("No PYTHON runner registered for check=%s code=%s", check, rule.code)
                continue
            try:
                produced = runner(rule, ctx, report_language) or []
            except Exception:  # noqa: BLE001
                logger.exception("PYTHON runner failed for %s (%s)", rule.code, check)
                continue
            for f in produced:
                if not f.source_layer:
                    f.source_layer = "rule_based"
                findings.append(f)
    finally:
        set_rkb_catalog(None)
    return findings
