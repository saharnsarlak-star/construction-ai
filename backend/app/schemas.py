from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import CountryCode, DocumentCategory, LanguageCode, RiskSeverity


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country: CountryCode = CountryCode.IR
    ui_language: LanguageCode = LanguageCode.FA
    report_language: LanguageCode = LanguageCode.FA
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    country: CountryCode | None = None
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
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: int
    name: str
    country: CountryCode
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

    model_config = {"from_attributes": True}


class AnalysisOut(BaseModel):
    id: int
    project_id: int
    status: str
    summary: str | None
    report_language: LanguageCode
    readiness_score: int
    counts: dict[str, int]
    findings: list[FindingOut]
    created_at: datetime


class AnalyzeRequest(BaseModel):
    report_language: LanguageCode | None = None


class HealthOut(BaseModel):
    status: Literal["ok"]
    app: str
