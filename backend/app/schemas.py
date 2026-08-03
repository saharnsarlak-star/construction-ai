from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType, RiskSeverity


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country: CountryCode = CountryCode.IR
    project_type: ProjectType = ProjectType.INFRASTRUCTURE
    ui_language: LanguageCode = LanguageCode.FA
    report_language: LanguageCode = LanguageCode.FA
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    country: CountryCode | None = None
    project_type: ProjectType | None = None
    ui_language: LanguageCode | None = None
    report_language: LanguageCode | None = None
    description: str | None = None


class DocumentOut(BaseModel):
    id: int
    category: DocumentCategory
    original_name: str
    content_type: str | None
    size_bytes: int
    has_text: bool
    ocr_applied: bool = False
    extraction_phase: str | None = None
    extraction_progress: int | None = None
    extraction_message: str | None = None
    needs_manual_review: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadErrorOut(BaseModel):
    filename: str
    detail: str


class UploadBatchOut(BaseModel):
    documents: list[DocumentOut] = []
    errors: list[UploadErrorOut] = []


class DocumentBulkDelete(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=500)
    # When True, allow deleting files whose names appear in existing findings.
    # Historical findings stay; source file is simply gone.
    force: bool = False


class BulkDeleteItemResult(BaseModel):
    document_id: int
    original_name: str | None = None
    status: Literal["deleted", "not_found", "blocked_referenced", "error"]
    detail: str | None = None


class DocumentBulkDeleteOut(BaseModel):
    deleted_count: int = 0
    failed_count: int = 0
    results: list[BulkDeleteItemResult] = []


class ProjectStandardOut(BaseModel):
    standard_code: str
    title: str
    standard_class: str
    publisher: str
    applicability_level: str
    is_selected: bool
    selected_by: str  # system_default | user_override
    check_target: str  # technical docs vs contract
    has_pdf: bool = False  # original file retained in catalog_standard_assets


class AuthMeOut(BaseModel):
    username: str
    role: Literal["admin", "user"]
    is_admin: bool


class CatalogStandardOut(BaseModel):
    standard_code: str
    title: str
    standard_class: str
    publisher: str | None
    original_name: str
    content_type: str | None
    size_bytes: int
    has_pdf: bool = True
    created_at: datetime


class ProjectStandardUpdateItem(BaseModel):
    standard_code: str
    is_selected: bool


class ProjectStandardsUpdate(BaseModel):
    items: list[ProjectStandardUpdateItem]


class ProjectOut(BaseModel):
    id: int
    name: str
    country: CountryCode
    project_type: ProjectType = ProjectType.INFRASTRUCTURE
    country_profile_code: str | None = None
    ui_language: LanguageCode
    report_language: LanguageCode
    description: str | None
    created_at: datetime
    documents: list[DocumentOut] = []

    model_config = {"from_attributes": True}


class FindingOut(BaseModel):
    id: int
    code: str
    category: str
    severity: RiskSeverity
    title: str
    description: str
    recommendation: str
    financial_impact: str | None
    schedule_impact: str | None
    evidence: str | None
    finding_category: str = "risk"
    risk_score: int | None = None
    source_excerpt: str | None = None
    cause_effect_chain: list[str] = []
    data_completeness_caveat: str | None = None
    estimated_impact: str | None = None
    source_layer: str | None = None
    confidence_score: int | None = None

    model_config = {"from_attributes": True}


class RelatedFindingHop(BaseModel):
    finding_id: int
    code: str
    title: str
    severity: str | None = None
    via_element_id: int | None = None
    path: list[dict] = []
    path_summary: str = ""


class RelatedFindingsChain(BaseModel):
    """Phase 5 additive knowledge-graph chain (does not modify Finding rows)."""

    anchor_finding_id: int
    anchor_finding_code: str
    anchor_title: str | None = None
    shared_element: dict
    documents: list[str] = []
    related_findings: list[RelatedFindingHop] = []
    hop_count: int = 0
    narrative: str = ""


class AnalysisOut(BaseModel):
    id: int
    project_id: int
    status: str
    summary: str | None
    report_language: LanguageCode
    readiness_score: int
    counts: dict[str, int]
    counts_risk: dict[str, int] | None = None
    aggregate_risk_score: int | None = None
    documents_with_limitations: int | None = None
    text_extraction_success_rate: float | None = None
    findings: list[FindingOut]
    # Phase 5 — additive cross-document risk chains (default empty when KG off)
    related_findings_chain: list[RelatedFindingsChain] = []
    created_at: datetime


class AnalyzeRequest(BaseModel):
    report_language: LanguageCode | None = None


class HealthOut(BaseModel):
    status: Literal["ok"]
    app: str


class RiskOut(BaseModel):
    id: int | None = None
    risk_id: str
    category: str
    description: str = ""
    probability: str | None = None
    cost_impact: str | None = None
    schedule_impact: str | None = None
    quality_impact: str | None = None
    safety_impact: str | None = None
    mitigation: str | None = None
    lessons_learned: str | None = None
    related_standards: list[str] = []
    related_documents: list[str] = []
    seed_batch: int | None = None
    version: int = 1
    is_active: bool = True
    source: str | None = None
    mapping_source: str | None = None


class RiskPatch(BaseModel):
    category: str | None = None
    description: str | None = None
    probability: str | None = None
    cost_impact: str | None = None
    schedule_impact: str | None = None
    quality_impact: str | None = None
    safety_impact: str | None = None
    mitigation: str | None = None
    lessons_learned: str | None = None
    related_standards: list[str] | None = None
    related_documents: list[str] | None = None
    is_active: bool | None = None


class RiskSeedOut(BaseModel):
    seed_dicts: int
    inserted: int
    skipped_existing: int
    table_count: int
    unique_seed_ids: int


class ExperienceOut(BaseModel):
    id: int
    experience_id: str
    title: str
    description: str = ""
    category: str = "lesson"
    origin_kind: str = "admin_curated"
    source: str | None = None
    author: str | None = None
    validation_status: str = "validated"
    confidence_level: str = "medium"
    related_risk_id: str | None = None
    related_risk_category: str | None = None
    related_project_types: list[str] = []
    recommended_prevention: str | None = None
    related_documents: list[str] = []
    related_outcomes: list[str] = []
    match_keywords: list[str] = []
    version: int = 1
    is_active: bool = True


class ExperienceCreate(BaseModel):
    title: str = Field(min_length=3, max_length=512)
    description: str = ""
    category: str = "lesson"
    origin_kind: str = "admin_curated"
    # Related Risk — accept either alias
    related_risk_id: str | None = None
    related_risk: str | None = None
    related_risk_category: str | None = None
    related_project_types: list[str] = []
    related_project_type: str | None = None  # single convenience field
    confidence_level: str = "medium"
    validation_status: str = "validated"
    recommended_prevention: str | None = None
    prevention: str | None = None  # alias
    match_keywords: list[str] = []
    source: str | None = None
    author: str | None = None
    experience_id: str | None = None


class ExperiencePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    origin_kind: str | None = None
    related_risk_id: str | None = None
    related_risk: str | None = None
    related_risk_category: str | None = None
    related_project_types: list[str] | None = None
    related_project_type: str | None = None
    confidence_level: str | None = None
    validation_status: str | None = None
    recommended_prevention: str | None = None
    prevention: str | None = None
    match_keywords: list[str] | None = None
    source: str | None = None
    author: str | None = None
    is_active: bool | None = None


class ExperienceBulkCreate(BaseModel):
    """Paste many lessons: either structured items or a raw multi-block text."""

    items: list[ExperienceCreate] = []
    raw_text: str | None = None  # blocks separated by --- or blank lines
    default_category: str | None = None
    default_project_types: list[str] = []
    auto_categorize: bool = True


class ExperienceBulkOut(BaseModel):
    created: list[ExperienceOut]
    created_count: int
    skipped: int = 0


class ExperienceSuggestOut(BaseModel):
    category: str
    match_keywords: list[str]
    title_suggestion: str | None = None
