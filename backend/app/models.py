import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
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
    RESIDENTIAL = "residential"
    HOSPITAL = "hospital"
    INDUSTRIAL = "industrial"
    INFRASTRUCTURE = "infrastructure"


class RiskSeverity(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[CountryCode] = mapped_column(
        Enum(CountryCode, values_callable=_enum_values, native_enum=False),
        default=CountryCode.IR,
    )
    project_type: Mapped[str] = mapped_column(
        String(64),
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

    analysis: Mapped["Analysis"] = relationship(back_populates="findings")
