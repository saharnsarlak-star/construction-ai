"""Standards Engine — SQLAlchemy models for ingested clauses and requirements.

Uses the existing ``catalog_standard_assets`` table as the standards catalog
(see ``CatalogStandardAsset`` in ``app.models``). Postgres-oriented: taxonomy
arrays use ``postgresql.ARRAY``.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import CatalogStandardAsset
from app.standards_engine.taxonomy import Discipline, enum_values


class RequirementType(str, enum.Enum):
    MANDATORY = "mandatory"
    PROHIBITION = "prohibition"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    CONDITIONAL = "conditional"
    RECOMMENDATION = "recommendation"


class StandardClause(Base):
    """One clause/paragraph extracted from a catalog standard document."""

    __tablename__ = "standard_clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    standard_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_standard_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clause_number: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    section: Mapped[str | None] = mapped_column(String(128), nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    slot_code: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    taxonomy_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    taxonomy_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    catalog_standard: Mapped[CatalogStandardAsset] = relationship(
        "CatalogStandardAsset",
        foreign_keys=[standard_id],
    )
    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="clause",
        cascade="all, delete-orphan",
    )


class Requirement(Base):
    """Structured requirement extracted from a clause and tagged with fixed taxonomy."""

    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clause_id: Mapped[int] = mapped_column(
        ForeignKey("standard_clauses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    discipline: Mapped[Discipline] = mapped_column(
        Enum(Discipline, values_callable=enum_values, native_enum=False),
        nullable=False,
    )
    # Multi-valued taxonomy axes — stored as English code arrays (see taxonomy.py).
    topic: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        server_default="{}",
    )
    element: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        server_default="{}",
    )
    material: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        server_default="{}",
    )
    # Finer-grained topic codes — free-form strings (see taxonomy.subtopics).
    subtopic: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(64)),
        nullable=True,
        server_default="{}",
    )
    requirement_type: Mapped[RequirementType] = mapped_column(
        Enum(RequirementType, values_callable=enum_values, native_enum=False),
        nullable=False,
    )
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conditions_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clause: Mapped["StandardClause"] = relationship(back_populates="requirements")
