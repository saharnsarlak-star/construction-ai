"""Document templates — country-specific shapes for the same CTKM document type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import CountryCode, DocumentCategory, ProjectType


@dataclass(frozen=True)
class DocumentTemplate:
    code: str
    document_category: DocumentCategory
    country: CountryCode | None  # None = global fallback
    project_type: ProjectType | None
    format_family: str
    extraction_profile_key: str
    schema_hint: dict[str, Any] = field(default_factory=dict)
    priority: int = 100


DOCUMENT_TEMPLATES: list[DocumentTemplate] = [
    # --- BOQ / quantities (uploaded under tender in MVP UI; template still country-aware) ---
    DocumentTemplate(
        code="BOQ_FEHREST_BAHA",
        document_category=DocumentCategory.TENDER,
        country=CountryCode.IR,
        project_type=None,
        format_family="fehrest_baha",
        extraction_profile_key="boq_fehrest",
        schema_hint={"canonical_items_path": "items", "native_path": "fehrest.items"},
        priority=10,
    ),
    DocumentTemplate(
        code="BOQ_GAEB",
        document_category=DocumentCategory.TENDER,
        country=CountryCode.DE,
        project_type=None,
        format_family="gaeb",
        extraction_profile_key="boq_gaeb",
        schema_hint={"canonical_items_path": "items", "native_path": "gaeb.positions"},
        priority=10,
    ),
    DocumentTemplate(
        code="BOQ_TRADE_CA",
        document_category=DocumentCategory.TENDER,
        country=CountryCode.CA,
        project_type=None,
        format_family="trade_boq",
        extraction_profile_key="boq_trade",
        schema_hint={"canonical_items_path": "items", "native_path": "trades.items"},
        priority=10,
    ),
    DocumentTemplate(
        code="BOQ_GENERIC",
        document_category=DocumentCategory.TENDER,
        country=None,
        project_type=None,
        format_family="generic",
        extraction_profile_key="boq_generic",
        schema_hint={"canonical_items_path": "items"},
        priority=100,
    ),
    # --- Contract / tender pack ---
    DocumentTemplate(
        code="CONTRACT_IR_PCC",
        document_category=DocumentCategory.TENDER,
        country=CountryCode.IR,
        project_type=None,
        format_family="iran_pcc",
        extraction_profile_key="contract_ir",
        schema_hint={"framework": "general_particular_conditions"},
        priority=20,
    ),
    DocumentTemplate(
        code="CONTRACT_DE_VOB",
        document_category=DocumentCategory.TENDER,
        country=CountryCode.DE,
        project_type=None,
        format_family="vob_bgb",
        extraction_profile_key="contract_de",
        schema_hint={"framework": "VOB/B+BGB"},
        priority=20,
    ),
    DocumentTemplate(
        code="CONTRACT_CA_CCDC",
        document_category=DocumentCategory.TENDER,
        country=CountryCode.CA,
        project_type=None,
        format_family="ccdc",
        extraction_profile_key="contract_ca",
        schema_hint={"framework": "CCDC"},
        priority=20,
    ),
    # --- Standards ---
    DocumentTemplate(
        code="STD_IR",
        document_category=DocumentCategory.STANDARD,
        country=CountryCode.IR,
        project_type=None,
        format_family="ir_nbr",
        extraction_profile_key="standard_generic",
        priority=10,
    ),
    DocumentTemplate(
        code="STD_DE_DIN",
        document_category=DocumentCategory.STANDARD,
        country=CountryCode.DE,
        project_type=None,
        format_family="din_vob",
        extraction_profile_key="standard_generic",
        priority=10,
    ),
    DocumentTemplate(
        code="STD_CA",
        document_category=DocumentCategory.STANDARD,
        country=CountryCode.CA,
        project_type=None,
        format_family="nbc_csa",
        extraction_profile_key="standard_generic",
        priority=10,
    ),
    DocumentTemplate(
        code="STD_GLOBAL",
        document_category=DocumentCategory.STANDARD,
        country=None,
        project_type=None,
        format_family="generic",
        extraction_profile_key="standard_generic",
        priority=100,
    ),
    # --- Schedule / drawings generic with country priority hooks ---
    DocumentTemplate(
        code="SCHEDULE_GENERIC",
        document_category=DocumentCategory.SCHEDULE,
        country=None,
        project_type=None,
        format_family="generic",
        extraction_profile_key="schedule_generic",
        priority=100,
    ),
    DocumentTemplate(
        code="DRAWING_GENERIC",
        document_category=DocumentCategory.DRAWING,
        country=None,
        project_type=None,
        format_family="generic",
        extraction_profile_key="drawing_generic",
        priority=100,
    ),
]


def resolve_document_template(
    *,
    category: DocumentCategory,
    country: CountryCode,
    project_type: ProjectType | None = None,
) -> DocumentTemplate:
    candidates = [t for t in DOCUMENT_TEMPLATES if t.document_category == category]
    scored: list[tuple[int, DocumentTemplate]] = []
    for t in candidates:
        if t.country is not None and t.country != country:
            continue
        if t.project_type is not None and project_type is not None and t.project_type != project_type:
            continue
        score = 0
        if t.country == country:
            score += 100
        if t.project_type is not None and t.project_type == project_type:
            score += 40
        score += max(0, 50 - t.priority)
        scored.append((score, t))
    if not scored:
        # ultimate fallback: any global for category else first
        globals_ = [t for t in candidates if t.country is None]
        return globals_[0] if globals_ else candidates[0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]
