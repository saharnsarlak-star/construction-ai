"""Seed Batch 2 — domain rules for remaining 4 of 10 canonical document types.

Wired into GLOBAL_RULES via rules_registry alongside Batch 1.
Does not replace seed_rules_batch1.py.

Prefixes (collision-free vs Batch 1):
  STD-SEED / RISK-STD-   Standards and Codes
  GEO-SEED / RISK-GEO-   Geotechnical Reports
  REQ-SEED / RISK-REQ-   Employer Requirements
  ADD-SEED / RISK-ADD-   Addenda
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models import DocumentCategory, RiskSeverity

if TYPE_CHECKING:
    from app.knowledge.rules_registry import RuleDef


def build_seed_batch2_rules() -> list[RuleDef]:
    # Lazy import avoids circular load with rules_registry
    from app.knowledge.rules_registry import RuleDef
    from app.knowledge.seed_i18n import localized_seed_fields

    def _seed(
        *,
        code: str,
        document_type: str,
        category: str,
        ownership_tag: str,
        ontology_entities: list[str],
        risk_id: str,
        description_en: str,
        title_en: str,
        severity: RiskSeverity,
        impact_fin: str,
        impact_sch: str,
        requires: DocumentCategory | None = None,
        applies: list[DocumentCategory] | None = None,
        check: str = "seed_pending",
        extra: dict[str, Any] | None = None,
    ) -> RuleDef:
        cfg: dict[str, Any] = {
            "seed_batch": 2,
            "document_type": document_type,
            "validation_category": category,
            "ownership_tag": ownership_tag,
            "ontology_entities": ontology_entities,
            "risk_id": risk_id,
            "check": check,
        }
        if extra:
            cfg.update(extra)
        title, description, recommendation = localized_seed_fields(code, title_en, description_en)
        return RuleDef(
            code=code,
            category=category.replace("-", "_"),
            severity=severity,
            title=title,
            description=description,
            recommendation=recommendation,
            financial_impact=impact_fin,
            schedule_impact=impact_sch,
            requires_category=requires,
            applies_to=applies or ([] if requires is None else [requires]),
            logic_config=cfg,
            keywords_any=[],
        )

    DT_STD = "Standards and Codes"
    DT_GEO = "Geotechnical Reports"
    DT_REQ = "Employer Requirements"
    DT_ADD = "Addenda"

    INTRA = "intra-document"
    INTER = "inter-document"
    STD = "standard-compliance"

    return [
        # ----- Standards and Codes -----
        # Operate on already-parsed StandardClause / StandardVersion — never re-parse standard text per project.
        _seed(
            code="STD-SEED-001",
            document_type=DT_STD,
            category=STD,
            ownership_tag="PYTHON",
            ontology_entities=["Standard", "StandardVersion", "Project"],
            risk_id="RISK-STD-SUPERSEDED-001",
            title_en="Project bound to superseded StandardVersion",
            description_en=(
                "Project is bound to a StandardVersion that is no longer is_current; "
                "a newer current version exists and analysis did not refresh the binding."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.STANDARD,
            check="standard_version_is_current",
            extra={"uses_preparsed_standard": True},
        ),
        _seed(
            code="STD-SEED-002",
            document_type=DT_STD,
            category=STD,
            ownership_tag="PYTHON",
            ontology_entities=["Standard", "StandardVersion", "Project"],
            risk_id="RISK-STD-MANDATORY-MISSING-001",
            title_en="Mandatory applicable Standard not selected/uploaded",
            description_en=(
                "A Standard marked mandatory for this country/project type "
                "(StandardApplicability / country_profiles defaults) is missing from the project."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.STANDARD,
            check="mandatory_standard_completeness",
            extra={"uses_preparsed_standard": True, "uses_country_profiles": True},
        ),
        _seed(
            code="STD-SEED-003",
            document_type=DT_STD,
            category=STD,
            ownership_tag="HYBRID",
            ontology_entities=["StandardClause", "StandardVersion", "Document", "Requirement", "Project"],
            risk_id="RISK-STD-CLAUSE-COMPLIANCE-001",
            title_en="No semantic evidence of compliance with applicable StandardClause",
            description_en=(
                "Python retrieves already-parsed StandardClause records; AI checks project document "
                "content for semantic compliance with the clause meaning (not merely citation of the standard name)."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.STANDARD,
            applies=[DocumentCategory.STANDARD, DocumentCategory.TENDER],
            check="standard_clause_semantic_compliance",
            extra={"uses_preparsed_standard": True, "never_reparses_standard_text": True},
        ),
        _seed(
            code="STD-SEED-004",
            document_type=DT_STD,
            category=INTER,
            ownership_tag="HYBRID",
            ontology_entities=["Standard", "StandardVersion", "Contract", "Contract Clause", "Project"],
            risk_id="RISK-STD-FRAMEWORK-CONFLICT-001",
            title_en="Selected Standards impose contradictory contractual frameworks",
            description_en=(
                "Two selected Standards conflict (e.g. Contract cites FIDIC while country profile "
                "mandates a different national contract framework). Python detects framework mismatch; AI explains."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="high",
            requires=DocumentCategory.STANDARD,
            applies=[DocumentCategory.STANDARD, DocumentCategory.TENDER],
            check="standard_framework_conflict",
            extra={
                "uses_preparsed_standard": True,
                "cross_document_types": ["Standards and Codes", "Contract Documents"],
            },
        ),
        _seed(
            code="STD-SEED-005",
            document_type=DT_STD,
            category=INTRA,
            ownership_tag="PYTHON",
            ontology_entities=["Standard", "StandardClause", "Document"],
            risk_id="RISK-STD-LOW-CONFIDENCE-001",
            title_en="Custom uploaded Standard has low extraction confidence",
            description_en=(
                "User-uploaded custom Standard OCR/extraction confidence is below threshold; "
                "parsed StandardClause records are unreliable for Rule Engine compliance checks."
            ),
            severity=RiskSeverity.MEDIUM,
            impact_fin="medium",
            impact_sch="low",
            requires=DocumentCategory.STANDARD,
            check="standard_extraction_confidence",
            extra={"confidence_gate_before_rule_engine": True},
        ),
        # ----- Geotechnical Reports -----
        _seed(
            code="GEO-SEED-001",
            document_type=DT_GEO,
            category=STD,
            ownership_tag="PYTHON",
            ontology_entities=["Document", "Project", "Location"],
            risk_id="RISK-GEO-MISSING-001",
            title_en="No Geotechnical Report uploaded where typically required",
            description_en=(
                "Completeness check: project type/site condition normally requires a Geotechnical Report, "
                "but none was uploaded."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="high",
            requires=DocumentCategory.TENDER,
            check="geotech_report_required",
            extra={"cdm_subtype_hint": ["geotech", "geotechnical_report", "soil_report"]},
        ),
        _seed(
            code="GEO-SEED-002",
            document_type=DT_GEO,
            category=INTRA,
            ownership_tag="AI",
            ontology_entities=["Document", "Document Section", "Constraint"],
            risk_id="RISK-GEO-GROUNDWATER-001",
            title_en="Groundwater table absent or insufficiently described",
            description_en="Semantic content check: groundwater table data missing or too vague in the report.",
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            check="geotech_groundwater_content",
            extra={"cdm_subtype_hint": ["geotech", "geotechnical_report"]},
        ),
        _seed(
            code="GEO-SEED-003",
            document_type=DT_GEO,
            category=INTER,
            ownership_tag="HYBRID",
            ontology_entities=["Document", "Drawing Sheet", "Foundation", "Material", "Constraint"],
            risk_id="RISK-GEO-VS-FOUNDATION-001",
            title_en="Foundation design inconsistent with stated soil bearing capacity",
            description_en=(
                "Cross-document: foundation design on Engineering Drawings conflicts with bearing capacity "
                "in the Geotechnical Report. Python detects numeric/parameter mismatch; AI explains risk."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="high",
            requires=DocumentCategory.TENDER,
            applies=[DocumentCategory.TENDER, DocumentCategory.DRAWING],
            check="geotech_vs_foundation_drawings",
            extra={
                "cdm_subtype_hint": ["geotech", "geotechnical_report"],
                "cross_document_types": ["Geotechnical Reports", "Engineering Drawings"],
            },
        ),
        _seed(
            code="GEO-SEED-004",
            document_type=DT_GEO,
            category=INTRA,
            ownership_tag="PYTHON",
            ontology_entities=["Document", "Project"],
            risk_id="RISK-GEO-STALE-001",
            title_en="Geotechnical Report date significantly older than project start",
            description_en=(
                "Report date minus project start exceeds configurable staleness threshold; "
                "site/soil conditions may have changed."
            ),
            severity=RiskSeverity.MEDIUM,
            impact_fin="medium",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            check="geotech_report_staleness",
            extra={
                "cdm_subtype_hint": ["geotech", "geotechnical_report"],
                "staleness_threshold_days_config_key": "geotech_max_age_days",
            },
        ),
        _seed(
            code="GEO-SEED-005",
            document_type=DT_GEO,
            category=INTRA,
            ownership_tag="HYBRID",
            ontology_entities=["Document", "Location", "Building", "Project"],
            risk_id="RISK-GEO-BOREHOLE-001",
            title_en="Insufficient boreholes relative to footprint/site area",
            description_en=(
                "Python compares borehole count/locations to area-based threshold; "
                "AI/expert knowledge judges whether the threshold is contextually reasonable."
            ),
            severity=RiskSeverity.MEDIUM,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            check="geotech_borehole_density",
            extra={"cdm_subtype_hint": ["geotech", "geotechnical_report"]},
        ),
        # ----- Employer Requirements -----
        # document_type = plural; ontology entity = singular "Employer Requirement"
        _seed(
            code="REQ-SEED-001",
            document_type=DT_REQ,
            category=INTER,
            ownership_tag="HYBRID",
            ontology_entities=["Employer Requirement", "Requirement", "Document Section"],
            risk_id="RISK-REQ-VS-SPEC-001",
            title_en="Employer Requirement conflicts with Technical Specification on same subject",
            description_en="Cross-document conflict between an Employer Requirement and a Technical Specification covering the same subject.",
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="high",
            requires=DocumentCategory.TENDER,
            check="er_vs_technical_specs",
            extra={
                "cdm_subtype_hint": ["employer_requirements", "er", "employers_requirements"],
                "cross_document_types": ["Employer Requirements", "Technical Specifications"],
            },
        ),
        _seed(
            code="REQ-SEED-002",
            document_type=DT_REQ,
            category=INTER,
            ownership_tag="PYTHON",
            ontology_entities=["Employer Requirement", "BOQ Item", "Drawing Sheet", "Drawing"],
            risk_id="RISK-REQ-UNFUNDED-001",
            title_en="Employer Requirement has no corresponding BOQ item or Drawing",
            description_en=(
                "Requirement references a deliverable/system with no matching BOQ item or Engineering Drawing "
                "(unfunded/unaddressed requirement)."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            applies=[DocumentCategory.TENDER, DocumentCategory.DRAWING],
            check="er_vs_boq_drawing_presence",
            extra={
                "cdm_subtype_hint": ["employer_requirements", "er"],
                "cross_document_types": [
                    "Employer Requirements",
                    "Bill of Quantities (BOQ)",
                    "Engineering Drawings",
                ],
            },
        ),
        _seed(
            code="REQ-SEED-003",
            document_type=DT_REQ,
            category=INTRA,
            ownership_tag="AI",
            ontology_entities=["Employer Requirement", "Requirement"],
            risk_id="RISK-REQ-VAGUE-001",
            title_en="Vague or unmeasurable performance requirement",
            description_en=(
                "Employer Requirement uses non-measurable language (e.g. 'high quality finish') "
                "without acceptance criteria."
            ),
            severity=RiskSeverity.MEDIUM,
            impact_fin="medium",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            check="er_vague_performance",
            extra={"cdm_subtype_hint": ["employer_requirements", "er"]},
        ),
        _seed(
            code="REQ-SEED-004",
            document_type=DT_REQ,
            category=INTER,
            ownership_tag="HYBRID",
            ontology_entities=["Employer Requirement", "StandardClause", "Standard", "Requirement"],
            risk_id="RISK-REQ-VS-STD-CLAUSE-001",
            title_en="Employer Requirement contradicts mandatory StandardClause",
            description_en=(
                "Employer Requirement conflicts with a mandatory clause from an applicable, "
                "already-parsed StandardClause (Standards and Codes)."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            applies=[DocumentCategory.TENDER, DocumentCategory.STANDARD],
            check="er_vs_standard_clause",
            extra={
                "cdm_subtype_hint": ["employer_requirements", "er"],
                "uses_preparsed_standard": True,
                "cross_document_types": ["Employer Requirements", "Standards and Codes"],
            },
        ),
        # ----- Addenda -----
        _seed(
            code="ADD-SEED-001",
            document_type=DT_ADD,
            category=INTER,
            ownership_tag="AI",
            ontology_entities=["Change", "Contract Clause", "Tender", "Document"],
            risk_id="RISK-ADD-IMPLICIT-SUPERSEDE-001",
            title_en="Addendum contradicts original clause without explicit supersession",
            description_en=(
                "Addendum content contradicts a Tender/Contract clause it appears to replace, "
                "without an explicit 'supersedes' ontology relationship."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="high",
            requires=DocumentCategory.TENDER,
            check="addendum_implicit_contradiction",
            extra={
                "cdm_subtype_hint": ["addendum", "addenda", "corrigendum"],
                "expects_ontology_relation": "supersedes",
                "cross_document_types": ["Addenda", "Tender Documents", "Contract Documents"],
            },
        ),
        _seed(
            code="ADD-SEED-002",
            document_type=DT_ADD,
            category=INTER,
            ownership_tag="PYTHON",
            ontology_entities=["Change", "Tender", "Milestone"],
            risk_id="RISK-ADD-AFTER-DEADLINE-001",
            title_en="Addendum issued after bid deadline without extension",
            description_en=(
                "Addendum issue date is after the stated bid/submission deadline and no explicit "
                "deadline extension is recorded (cross-document with Tender Documents)."
            ),
            severity=RiskSeverity.HIGH,
            impact_fin="medium",
            impact_sch="high",
            requires=DocumentCategory.TENDER,
            check="addendum_after_deadline",
            extra={
                "cdm_subtype_hint": ["addendum", "addenda"],
                "cross_document_types": ["Addenda", "Tender Documents"],
            },
        ),
        _seed(
            code="ADD-SEED-003",
            document_type=DT_ADD,
            category=INTER,
            ownership_tag="PYTHON",
            ontology_entities=["Change", "BOQ Item", "Drawing Sheet", "Drawing"],
            risk_id="RISK-ADD-ORPHAN-001",
            title_en="Addendum not reflected in final BOQ or Engineering Drawings",
            description_en="Orphaned addendum: content not incorporated into BOQ or drawings (cross-document absence).",
            severity=RiskSeverity.HIGH,
            impact_fin="high",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            applies=[DocumentCategory.TENDER, DocumentCategory.DRAWING],
            check="addendum_orphaned",
            extra={
                "cdm_subtype_hint": ["addendum", "addenda"],
                "cross_document_types": [
                    "Addenda",
                    "Bill of Quantities (BOQ)",
                    "Engineering Drawings",
                ],
            },
        ),
        _seed(
            code="ADD-SEED-004",
            document_type=DT_ADD,
            category=INTRA,
            ownership_tag="PYTHON",
            ontology_entities=["Change", "Document"],
            risk_id="RISK-ADD-SEQUENCE-GAP-001",
            title_en="Numbering gap in Addenda sequence",
            description_en="Addenda sequence has a gap (e.g. 1 and 3 present, 2 missing or not uploaded).",
            severity=RiskSeverity.MEDIUM,
            impact_fin="medium",
            impact_sch="medium",
            requires=DocumentCategory.TENDER,
            check="addendum_sequence_gap",
            extra={"cdm_subtype_hint": ["addendum", "addenda"]},
        ),
    ]


# ---------------------------------------------------------------------------
# New Risk IDs for Part 5 RKB (Batch 2) — all new; no Batch 1 reuse required
# ---------------------------------------------------------------------------

NEW_RISK_IDS_BATCH2: list[dict[str, str]] = [
    {
        "risk_id": "RISK-STD-SUPERSEDED-001",
        "category": "compliance",
        "description": "Project bound to superseded StandardVersion while a newer is_current exists.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-STD-MANDATORY-MISSING-001",
        "category": "compliance",
        "description": "Mandatory Standard for country/project type not selected or uploaded.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-STD-CLAUSE-COMPLIANCE-001",
        "category": "compliance",
        "description": "Project content lacks semantic compliance with applicable pre-parsed StandardClause.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-STD-FRAMEWORK-CONFLICT-001",
        "category": "claim",
        "description": "Selected Standards impose contradictory contractual frameworks.",
        "cost_impact": "high",
        "schedule_impact": "high",
        "quality_impact": "medium",
    },
    {
        "risk_id": "RISK-STD-LOW-CONFIDENCE-001",
        "category": "quality",
        "description": "Custom Standard extraction confidence too low for reliable StandardClause use.",
        "cost_impact": "medium",
        "schedule_impact": "low",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-GEO-MISSING-001",
        "category": "constructability",
        "description": "Geotechnical Report missing where project type/site typically requires one.",
        "cost_impact": "high",
        "schedule_impact": "high",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-GEO-GROUNDWATER-001",
        "category": "quality",
        "description": "Groundwater table absent or insufficiently described in geotech report.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-GEO-VS-FOUNDATION-001",
        "category": "constructability",
        "description": "Foundation design inconsistent with stated soil bearing capacity.",
        "cost_impact": "high",
        "schedule_impact": "high",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-GEO-STALE-001",
        "category": "quality",
        "description": "Geotechnical Report significantly older than project start (staleness).",
        "cost_impact": "medium",
        "schedule_impact": "medium",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-GEO-BOREHOLE-001",
        "category": "constructability",
        "description": "Borehole count/locations insufficient relative to footprint/site area.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-REQ-VS-SPEC-001",
        "category": "claim",
        "description": "Employer Requirement conflicts with Technical Specification on same subject.",
        "cost_impact": "high",
        "schedule_impact": "high",
        "quality_impact": "medium",
    },
    {
        "risk_id": "RISK-REQ-UNFUNDED-001",
        "category": "cost",
        "description": "Employer Requirement has no corresponding BOQ item or Engineering Drawing.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "medium",
    },
    {
        "risk_id": "RISK-REQ-VAGUE-001",
        "category": "claim",
        "description": "Vague or unmeasurable Employer performance requirement.",
        "cost_impact": "medium",
        "schedule_impact": "medium",
        "quality_impact": "medium",
    },
    {
        "risk_id": "RISK-REQ-VS-STD-CLAUSE-001",
        "category": "compliance",
        "description": "Employer Requirement contradicts mandatory applicable StandardClause.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "high",
    },
    {
        "risk_id": "RISK-ADD-IMPLICIT-SUPERSEDE-001",
        "category": "claim",
        "description": "Addendum contradicts original clause without explicit supersedes relationship.",
        "cost_impact": "high",
        "schedule_impact": "high",
        "quality_impact": "low",
    },
    {
        "risk_id": "RISK-ADD-AFTER-DEADLINE-001",
        "category": "procurement",
        "description": "Addendum issued after bid deadline without explicit deadline extension.",
        "cost_impact": "medium",
        "schedule_impact": "high",
        "quality_impact": "low",
    },
    {
        "risk_id": "RISK-ADD-ORPHAN-001",
        "category": "cost",
        "description": "Addendum not incorporated into final BOQ or Engineering Drawings.",
        "cost_impact": "high",
        "schedule_impact": "medium",
        "quality_impact": "medium",
    },
    {
        "risk_id": "RISK-ADD-SEQUENCE-GAP-001",
        "category": "procurement",
        "description": "Gap in Addenda numbering sequence (missing intermediate addendum).",
        "cost_impact": "medium",
        "schedule_impact": "medium",
        "quality_impact": "low",
    },
]
