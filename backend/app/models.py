import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class CountryCode(str, enum.Enum):
    IR = "IR"
    DE = "DE"
    CA = "CA"
    EU = "EU"


class LanguageCode(str, enum.Enum):
    FA = "fa"
    EN = "en"
    DE = "de"
    FR = "fr"


class DocumentCategory(str, enum.Enum):
    TENDER = "tender"
    DRAWING = "drawing"
    SCHEDULE = "schedule"
    STANDARD = "standard"


class ProjectType(str, enum.Enum):
    """International construction / infrastructure project categories."""

    RESIDENTIAL = "residential"
    OFFICE = "office"
    COMMERCIAL = "commercial"
    MIXED_USE = "mixed_use"
    HOSPITAL = "hospital"
    EDUCATIONAL = "educational"
    HOSPITALITY = "hospitality"
    INDUSTRIAL = "industrial"
    WAREHOUSE = "warehouse"
    RETAIL = "retail"
    CULTURAL = "cultural"
    SPORTS = "sports"
    DATA_CENTER = "data_center"
    LABORATORY = "laboratory"
    INFRASTRUCTURE = "infrastructure"
    ROAD_HIGHWAY = "road_highway"
    BRIDGE = "bridge"
    TUNNEL = "tunnel"
    RAILWAY = "railway"
    AIRPORT = "airport"
    PORT_MARINE = "port_marine"
    DAM_WATER = "dam_water"
    WATER_WASTEWATER = "water_wastewater"
    POWER_ENERGY = "power_energy"
    OIL_GAS = "oil_gas"
    TELECOM = "telecom"
    LANDSCAPE_URBAN = "landscape_urban"
    RENOVATION_FITOUT = "renovation_fitout"
    OTHER = "other"


class RiskSeverity(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class AppUser(Base):
    """Minimal end-user for Phase 0 standards access control (not full multi-tenant IAM)."""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=_enum_values, native_enum=False),
        nullable=False,
        default=UserRole.USER,
    )
    api_token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogStandardAsset(Base):
    """Original PDF (or office file) for a catalog standard — retained for user download."""

    __tablename__ = "catalog_standard_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    standard_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    title_fa: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title_de: Mapped[str | None] = mapped_column(String(512), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    standard_class: Mapped[str] = mapped_column(String(32), default="technical")
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[CountryCode] = mapped_column(
        Enum(CountryCode, values_callable=_enum_values, native_enum=False),
        default=CountryCode.IR,
    )
    project_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=ProjectType.INFRASTRUCTURE.value,
        server_default="infrastructure",
    )
    country_profile_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ui_language: Mapped[LanguageCode] = mapped_column(
        Enum(LanguageCode, values_callable=_enum_values, native_enum=False),
        default=LanguageCode.FA,
    )
    report_language: Mapped[LanguageCode] = mapped_column(
        Enum(LanguageCode, values_callable=_enum_values, native_enum=False),
        default=LanguageCode.FA,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    documents: Mapped[list["Document"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    project_standards: Mapped[list["ProjectStandard"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    parties: Mapped[list["Party"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    elements: Mapped[list["ProjectElement"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    ontology_edges: Mapped[list["OntologyEdge"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectStandard(Base):
    """Per-project standard selection (catalog codes + user overrides)."""

    __tablename__ = "project_standards"
    __table_args__ = (UniqueConstraint("project_id", "standard_code", name="uq_project_standard"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    standard_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True)
    selected_by: Mapped[str] = mapped_column(String(32), default="system_default")
    applicability_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    standard_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="project_standards")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, values_callable=_enum_values, native_enum=False),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="documents")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(50), default="completed")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_language: Mapped[LanguageCode] = mapped_column(
        Enum(LanguageCode, values_callable=_enum_values, native_enum=False),
        default=LanguageCode.FA,
    )
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="analyses")
    findings: Mapped[list["Finding"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[RiskSeverity] = mapped_column(
        Enum(RiskSeverity, values_callable=_enum_values, native_enum=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    financial_impact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schedule_impact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding_category: Mapped[str | None] = mapped_column(String(32), nullable=True, default="risk")
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    cause_effect_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_completeness_caveat: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_impact: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Phase 3+: rule_based | llm_based | hybrid (additive; None = legacy keyword findings)
    source_layer: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="findings")


# ----- Phase 2 ontology (additive; gated by ONTOLOGY_ENABLED) -----


class Party(Base):
    """Canonical project party (GAP-01). Roles are views via party_role, not separate tables."""

    __tablename__ = "parties"
    __table_args__ = (
        UniqueConstraint("project_id", "legal_name", "party_role", name="uq_party_project_name_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(512), nullable=False)
    # Free string (GAP-11): employer | contractor | bidder | consultant | engineer | …
    party_role: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    contact_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="parties")


class ProjectElement(Base):
    """Project-scoped Element Registry (GAP-05): one real-world object across documents."""

    __tablename__ = "project_elements"
    __table_args__ = (
        UniqueConstraint("project_id", "match_key", name="uq_element_project_match_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    element_type: Mapped[str] = mapped_column(String(128), nullable=False, default="element")
    name_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    type_mark: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ifc_global_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Deterministic key when IFC guid absent: e.g. "wall:wall-a" or "a-101|wall:w-01"
    match_key: Mapped[str] = mapped_column(String(255), nullable=False)
    fire_rating: Mapped[str | None] = mapped_column(String(64), nullable=True)
    host_level: Mapped[str | None] = mapped_column(String(128), nullable=True)
    material_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drawing_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="elements")
    document_refs: Mapped[list["ElementDocumentRef"]] = relationship(
        back_populates="element", cascade="all, delete-orphan"
    )


class ElementDocumentRef(Base):
    """Provenance: which documents/local sources resolve to one ProjectElement."""

    __tablename__ = "element_document_refs"
    __table_args__ = (
        UniqueConstraint(
            "element_id",
            "document_id",
            "source_kind",
            "source_local_id",
            name="uq_element_doc_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    element_id: Mapped[int] = mapped_column(
        ForeignKey("project_elements.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    # ifc_element | boq_item | contract_clause | drawing_label | cdm_text
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_local_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    element: Mapped["ProjectElement"] = relationship(back_populates="document_refs")


class OntologyEdge(Base):
    """Project-scoped graph edge; predicate is free string from UNION_PREDICATES (expandable)."""

    __tablename__ = "ontology_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    from_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_id: Mapped[str] = mapped_column(String(128), nullable=False)
    to_type: Mapped[str] = mapped_column(String(64), nullable=False)
    to_id: Mapped[str] = mapped_column(String(128), nullable=False)
    predicate: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # python | ai | hybrid
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="python")
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="ontology_edges")


class Risk(Base):
    """Platform-level Risk Knowledge Base record (Part 5 RKB). Not project-scoped."""

    __tablename__ = "risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    risk_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="claim")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Default priors: low | medium | high (expandable free string)
    probability: Mapped[str | None] = mapped_column(String(32), nullable=True, default="medium")
    cost_impact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schedule_impact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quality_impact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    safety_impact: Mapped[str | None] = mapped_column(String(32), nullable=True, default="low")
    mitigation: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON arrays of codes / document-type hints
    related_standards_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_documents_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed_batch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExperienceKnowledgeItem(Base):
    """Human Construction Experience Knowledge (Part 6 / GAP-02 umbrella).

    Platform-level (not project-scoped). origin_kind reconciles ExtractedInsight /
    LessonsLearned / ExpertReview / ProjectOutcome without parallel taxonomies.
    Free-string origin_kind (not closed SQL ENUM — GAP-11).
    """

    __tablename__ = "experience_knowledge_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable public id e.g. EXP-HOSP-MEP-001 (auto if omitted)
    experience_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="lesson")
    # admin_curated | external_extracted | expert_reviewed | project_derived (+ Part 6 aliases)
    origin_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="admin_curated")
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # draft | pending_review | validated | rejected | archived
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False, default="validated")
    # low | medium | high (or 0–100 as string)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    related_risk_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    related_risk_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # JSON array of ProjectType values, e.g. ["hospital","laboratory"]
    related_project_types_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_prevention: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_documents_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_outcomes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array of keywords/phrases used to scan project document text
    match_keywords_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
