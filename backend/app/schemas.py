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

    model_config = {"from_attributes": True}


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
    created_at: datetime


class AnalyzeRequest(BaseModel):
    report_language: LanguageCode | None = None


class HealthOut(BaseModel):
    status: Literal["ok"]
    app: str
