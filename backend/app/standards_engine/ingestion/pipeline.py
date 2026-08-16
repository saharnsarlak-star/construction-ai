"""Standards Engine ingestion pipeline — parse, classify, extract, persist, check gaps."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, init_db
from app.models import CatalogStandardAsset
from app.services import storage as file_storage
from app.services.rule_engine.llm_client import LLMClient, LLMNotConfiguredError
from app.standards_engine.compliance.gap_checker import check_standard_coverage
from app.standards_engine.ingestion.catalog_metadata import (
    merge_catalog_metadata,
    parse_catalog_file_metadata,
)
from app.standards_engine.ingestion.clause_parser import (
    filter_substantive_clauses,
    parse_standards_file,
    parse_standards_pages,
    parse_standards_text,
)
from app.standards_engine.ingestion.pdf_extract import extract_catalog_standard_pages
from app.standards_engine.ingestion.requirement_validate import validate_requirements
from app.standards_engine.models import Requirement, RequirementType, StandardClause
from app.standards_engine.taxonomy import Discipline, TaxonomyAxis, codes_for_axis

_MAX_LLM_ATTEMPTS = 5
_RETRY_BACKOFF_SECONDS = (2, 4, 8, 16)

_UNIT_FA_TO_EN = {
    "سانتیمتر": "cm",
    "سانتی‌متر": "cm",
    "متر": "m",
    "میلیمتر": "mm",
    "میلی‌متر": "mm",
    "کیلوگرم": "kg",
    "درصد": "percent",
    "درجه": "degree",
}

T = TypeVar("T")


def _call_llm_with_retry(fn: Callable[[], T]) -> T:
    """Call ``fn`` with exponential backoff on transient network errors."""
    last_exc: httpx.ConnectError | httpx.TimeoutException | None = None
    for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
        try:
            return fn()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt >= _MAX_LLM_ATTEMPTS:
                raise
            delay = _RETRY_BACKOFF_SECONDS[attempt - 1]
            print(
                f"network error, retrying in {delay}s... "
                f"(attempt {attempt + 1}/{_MAX_LLM_ATTEMPTS})"
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _allowed_requirement_types() -> list[str]:
    return [m.value for m in RequirementType]


def _taxonomy_prompt_block() -> str:
    """Build allowed-code lists from taxonomy.py (auto-updates when taxonomy changes)."""
    lines = [
        "Allowed taxonomy codes (use ONLY these exact English snake_case strings):",
        f"- discipline (exactly one): {', '.join(codes_for_axis(TaxonomyAxis.DISCIPLINE))}",
        f"- topic (zero or more): {', '.join(codes_for_axis(TaxonomyAxis.TOPIC))}",
        f"- element (zero or more, may be empty): {', '.join(codes_for_axis(TaxonomyAxis.ELEMENT))}",
        f"- material (zero or more, may be empty): {', '.join(codes_for_axis(TaxonomyAxis.MATERIAL))}",
    ]
    return "\n".join(lines)


def parse_sample_file(path: str) -> list[dict[str, Any]]:
    """Parse a standards clause file (sample markers or numbered PDF-style text)."""
    return parse_standards_file(path, mode="auto")


async def _clause_already_saved(
    session: AsyncSession,
    *,
    catalog_standard_id: int,
    clause_number: str,
) -> bool:
    row = (
        await session.execute(
            select(StandardClause.id).where(
                StandardClause.standard_id == catalog_standard_id,
                StandardClause.clause_number == clause_number,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def _clear_catalog_clauses(session: AsyncSession, catalog_standard_id: int) -> int:
    """Remove all ingested clauses (and requirements) for a catalog standard."""
    result = await session.execute(
        delete(StandardClause).where(StandardClause.standard_id == catalog_standard_id)
    )
    await session.commit()
    return int(result.rowcount or 0)


async def _apply_catalog_metadata_from_text(
    session: AsyncSession,
    asset: CatalogStandardAsset | None,
    raw_text: str,
) -> None:
    """Populate missing catalog fields from file headers (country-agnostic)."""
    if asset is None:
        return
    meta = parse_catalog_file_metadata(raw_text)
    merged = merge_catalog_metadata(
        {
            "country_code": asset.country_code,
            "standard_version": asset.standard_version,
            "effective_date": asset.effective_date,
            "publisher": asset.publisher,
            "title_fa": asset.title_fa,
        },
        meta,
    )
    if merged.get("country_code"):
        asset.country_code = merged["country_code"]
    if merged.get("standard_version"):
        asset.standard_version = merged["standard_version"]
    if merged.get("effective_date"):
        asset.effective_date = merged["effective_date"]
    if merged.get("publisher"):
        asset.publisher = merged["publisher"]
    if merged.get("title_fa") and not asset.title_fa:
        asset.title_fa = merged["title_fa"]
    await session.commit()


async def _persist_clauses_loop(
    session: AsyncSession,
    *,
    catalog_id: int,
    standard_code: str,
    clauses: list[dict[str, Any]],
    skip_existing: bool = True,
) -> tuple[int, int, int]:
    """Classify, extract, save. Returns (saved_clauses, saved_requirements, skipped)."""
    saved_clauses = 0
    saved_requirements = 0
    skipped = 0

    for clause in clauses:
        clause_number = str(clause.get("clause_number") or "").strip() or "unknown"

        if skip_existing:
            async with SessionLocal() as check_session:
                if await _clause_already_saved(
                    check_session, catalog_standard_id=catalog_id, clause_number=clause_number
                ):
                    print(f"Skip existing clause {clause_number}")
                    skipped += 1
                    continue

        if _clause_text_len(clause) < 40:
            print(f"Skipping clause {clause_number}: body too short for extraction")
            skipped += 1
            continue

        # LLM calls can take 30s+ — do not hold a DB connection open while waiting.
        taxonomy = classify_clause(clause)
        if taxonomy.get("error"):
            print(f"Skipping clause {clause_number}: {taxonomy['error']}")
            skipped += 1
            continue

        requirements = extract_requirements(clause)
        requirements, val_warnings = validate_requirements(
            requirements,
            clause_number=clause_number,
            locale="auto",
        )
        for w in val_warnings:
            print(f"  validate warning [{w.get('code')}]: {w.get('message')}")

        async with SessionLocal() as save_session:
            clause_id = await save_clause_with_requirements(
                save_session,
                catalog_standard_id=catalog_id,
                clause=clause,
                taxonomy=taxonomy,
                requirements=requirements,
            )
        saved_clauses += 1
        saved_requirements += len(requirements)
        print(
            f"Saved clause {clause_number} (id={clause_id}) "
            f"with {len(requirements)} requirement(s)"
        )

    return saved_clauses, saved_requirements, skipped


async def load_requirements_for_standard(
    session: AsyncSession,
    *,
    standard_code: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Load persisted requirements for a catalog standard (for compliance checks)."""
    asset = (
        await session.execute(
            select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == standard_code)
        )
    ).scalar_one_or_none()
    if asset is None:
        return standard_code, []

    rows = (
        await session.execute(
            select(Requirement, StandardClause.clause_number, StandardClause.source_page)
            .join(StandardClause, Requirement.clause_id == StandardClause.id)
            .where(StandardClause.standard_id == asset.id)
        )
    ).all()

    out: list[dict[str, Any]] = []
    for req, clause_number, clause_source_page in rows:
        out.append(
            {
                "id": req.id,
                "clause_number": clause_number,
                "requirement_text": req.requirement_text,
                "requirement_type": req.requirement_type.value
                if hasattr(req.requirement_type, "value")
                else str(req.requirement_type),
                "min_value": req.min_value,
                "max_value": req.max_value,
                "unit": req.unit,
                "topic": list(req.topic or []),
                "source_page": clause_source_page,
            }
        )
    return standard_code, out


def _build_classify_prompts(clause: dict[str, Any]) -> tuple[str, str]:
    system = (
        "You are an engineering standards analyst. Classify construction standard clauses "
        "using ONLY the allowed taxonomy codes provided. Do NOT extract requirements — "
        "taxonomy only. Return ONLY valid JSON — no markdown, no commentary."
    )
    user_payload = {
        "task": "classify_standard_clause_taxonomy",
        "clause_number": clause.get("clause_number"),
        "title": clause.get("title"),
        "chapter": clause.get("chapter"),
        "section": clause.get("section"),
        "raw_text": clause.get("raw_text") or "",
        "taxonomy": {
            "discipline": codes_for_axis(TaxonomyAxis.DISCIPLINE),
            "topic": codes_for_axis(TaxonomyAxis.TOPIC),
            "element": codes_for_axis(TaxonomyAxis.ELEMENT),
            "material": codes_for_axis(TaxonomyAxis.MATERIAL),
        },
        "output_schema": {
            "discipline": "string — exactly one allowed discipline code",
            "topic": "string[] — zero or more allowed topic codes",
            "element": "string[] — zero or more allowed element codes (may be empty)",
            "material": "string[] — zero or more allowed material codes (may be empty)",
        },
    }
    user = (
        f"{_taxonomy_prompt_block()}\n\n"
        "Return ONLY a JSON object matching output_schema.\n"
        "Use empty arrays [] when element or material do not apply.\n\n"
        f"Clause payload:\n{json.dumps(user_payload, ensure_ascii=False, indent=2)}"
    )
    return system, user


def _build_extract_requirements_prompts(clause: dict[str, Any]) -> tuple[str, str]:
    system = (
        "You are an engineering standards analyst. Extract every distinct requirement from "
        "the clause text as separate structured items. Return ONLY valid JSON — no markdown, "
        "no commentary."
    )
    user_payload = {
        "task": "extract_standard_clause_requirements",
        "clause_number": clause.get("clause_number"),
        "title": clause.get("title"),
        "chapter": clause.get("chapter"),
        "section": clause.get("section"),
        "raw_text": clause.get("raw_text") or "",
        "requirement_types": _allowed_requirement_types(),
        "item_schema": {
            "requirement_type": "string — exactly one allowed requirement_type",
            "requirement_text": "string — concise requirement statement in Persian",
            "min_value": "number | null — numeric lower bound if stated",
            "max_value": "number | null — numeric upper bound if stated",
            "unit": "string | null — short English symbol only (e.g. m, cm, kg/m2, degree)",
            "conditions_text": "string | null — conditions/applicability in Persian",
        },
        "output_schema": {
            "requirements": "array of item_schema objects — one entry per distinct requirement",
        },
    }
    user = (
        f"Allowed requirement_type values: {', '.join(_allowed_requirement_types())}\n\n"
        "Return ONLY a JSON object: {\"requirements\": [ ... ]}.\n"
        "IMPORTANT: If the clause contains multiple separate numeric limits or obligations "
        "(e.g. several different minimum/maximum values for different parameters), output "
        "each as a SEPARATE item in the requirements array — never merge them into one "
        "combined item.\n"
        "unit must always be a short standardized symbol in English — examples: m, cm, mm, "
        "kg, kg/m2, kg/m3, ton, degree, percent, day, hour, mpa, kg/cm2. NEVER return a "
        "Persian word for the unit (e.g. never 'سانتیمتر' or 'متر') — always convert to its "
        "English symbol (e.g. 'cm', 'm').\n"
        "If a single requirement states BOTH a lower and upper bound for the SAME parameter "
        "(e.g. 'between 30 and 45 degrees'), output it as ONE item with "
        "requirement_type='conditional', both min_value and max_value set, and unit set once. "
        "Do NOT split a single min-max range into two separate items. Only use "
        "requirement_type='minimum' when ONLY a lower bound is stated (no upper bound), and "
        "'maximum' when ONLY an upper bound is stated (no lower bound).\n"
        "Use null for min_value, max_value, unit, conditions_text when not applicable.\n"
        "If the clause has no extractable requirement (e.g. heading-only), return "
        "{\"requirements\": []}.\n\n"
        f"Clause payload:\n{json.dumps(user_payload, ensure_ascii=False, indent=2)}"
    )
    return system, user


def _filter_codes(values: object, allowed: set[str]) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        code = str(v).strip().lower()
        if code in allowed and code not in out:
            out.append(code)
    return out


def _float_or_none(val: object) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _normalize_taxonomy(parsed: dict[str, Any]) -> dict[str, Any]:
    """Keep only allowed taxonomy codes."""
    discipline_allowed = set(codes_for_axis(TaxonomyAxis.DISCIPLINE))
    topic_allowed = set(codes_for_axis(TaxonomyAxis.TOPIC))
    element_allowed = set(codes_for_axis(TaxonomyAxis.ELEMENT))
    material_allowed = set(codes_for_axis(TaxonomyAxis.MATERIAL))

    discipline = str(parsed.get("discipline") or "").strip().lower()
    if discipline not in discipline_allowed:
        discipline = ""

    return {
        "discipline": discipline,
        "topic": _filter_codes(parsed.get("topic"), topic_allowed),
        "element": _filter_codes(parsed.get("element"), element_allowed),
        "material": _filter_codes(parsed.get("material"), material_allowed),
    }


def _normalize_requirement_item(item: dict[str, Any]) -> dict[str, Any]:
    req_types = set(_allowed_requirement_types())
    requirement_type = str(item.get("requirement_type") or "").strip().lower()
    if requirement_type not in req_types:
        requirement_type = RequirementType.MANDATORY.value

    unit_raw = str(item.get("unit")).strip() if item.get("unit") else None
    unit = _UNIT_FA_TO_EN.get(unit_raw, unit_raw) if unit_raw else None

    return {
        "requirement_type": requirement_type,
        "requirement_text": str(item.get("requirement_text") or "").strip(),
        "min_value": _float_or_none(item.get("min_value")),
        "max_value": _float_or_none(item.get("max_value")),
        "unit": unit,
        "conditions_text": (
            str(item.get("conditions_text")).strip() if item.get("conditions_text") else None
        ),
    }


def _normalize_requirements(parsed: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if parsed is None:
        return []
    raw_items: list[Any]
    if isinstance(parsed, list):
        raw_items = parsed
    elif isinstance(parsed, dict):
        raw_items = parsed.get("requirements") or []
        if not isinstance(raw_items, list):
            raw_items = []
    else:
        return []

    out: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            normalized = _normalize_requirement_item(item)
            if normalized["requirement_text"]:
                out.append(normalized)
    return out


def classify_clause(
    clause: dict[str, Any],
    *,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Classify one clause via LLM — taxonomy only (discipline, topic, element, material)."""
    client = llm or LLMClient()
    system, user = _build_classify_prompts(clause)
    call_key = f"std_clause_taxonomy_{clause.get('clause_number', 'unknown')}"

    try:
        resp = _call_llm_with_retry(
            lambda: client.chat_json(
                system=system, user=user, call_key=call_key, temperature=0.0
            )
        )
    except LLMNotConfiguredError as exc:
        return {"error": str(exc)}

    parsed = resp.parsed or {}
    return _normalize_taxonomy(parsed)


def extract_requirements(
    clause: dict[str, Any],
    *,
    llm: LLMClient | None = None,
) -> list[dict[str, Any]]:
    """Extract all distinct requirements from one clause via a separate LLM call."""
    client = llm or LLMClient()
    system, user = _build_extract_requirements_prompts(clause)
    call_key = f"std_clause_requirements_{clause.get('clause_number', 'unknown')}"

    try:
        resp = _call_llm_with_retry(
            lambda: client.chat_json(
                system=system, user=user, call_key=call_key, temperature=0.0
            )
        )
    except LLMNotConfiguredError:
        return []

    return _normalize_requirements(resp.parsed)


def _default_sample_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "samples"
        / "sample_clause_2-2-3.txt"
    )


def _clause_text_len(clause: dict[str, Any]) -> int:
    title = str(clause.get("title") or "").strip()
    body = str(clause.get("raw_text") or "").strip()
    if title and body.startswith(title):
        body = body[len(title) :].strip()
    return len(body or title)


def _clause_raw_text(clause: dict[str, Any]) -> str:
    parts: list[str] = []
    title = str(clause.get("title") or "").strip()
    body = str(clause.get("raw_text") or "").strip()
    if title:
        parts.append(title)
    if body:
        parts.append(body)
    return "\n".join(parts) if parts else "(empty)"


def _discipline_from_taxonomy(taxonomy: dict[str, Any]) -> Discipline:
    code = str(taxonomy.get("discipline") or "").strip().lower()
    try:
        return Discipline(code)
    except ValueError:
        return Discipline.HSE


def _requirement_type_from_dict(item: dict[str, Any]) -> RequirementType:
    code = str(item.get("requirement_type") or RequirementType.MANDATORY.value).strip().lower()
    try:
        return RequirementType(code)
    except ValueError:
        return RequirementType.MANDATORY


async def get_or_create_catalog_standard(
    session: AsyncSession,
    *,
    standard_code: str,
    country_code: str,
    title_fa: str,
    publisher: str | None,
    standard_class: str,
) -> int:
    """Return catalog_standard_assets.id for ``standard_code``, creating a placeholder row if needed."""
    result = await session.execute(
        select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == standard_code)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing.id

    asset = CatalogStandardAsset(
        standard_code=standard_code,
        title=title_fa.strip() or standard_code,
        title_fa=title_fa,
        publisher=publisher,
        standard_class=(standard_class or "technical").strip() or "technical",
        country_code=country_code,
        original_name="manual-entry",
        stored_path=f"manual/{standard_code}",
        size_bytes=0,
    )
    session.add(asset)
    await session.flush()
    return asset.id


async def save_clause_with_requirements(
    session: AsyncSession,
    *,
    catalog_standard_id: int,
    clause: dict[str, Any],
    taxonomy: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> int:
    """Persist one clause and its extracted requirements; commit and return clause id."""
    from app.tender_taxonomy.standard_codes import clause_slot_code, resolve_family_code
    from app.tender_taxonomy.standard_mapper import map_clause_to_taxonomy

    discipline = _discipline_from_taxonomy(taxonomy)
    clause_number = str(clause.get("clause_number") or "").strip() or "unknown"

    asset = (
        await session.execute(
            select(CatalogStandardAsset).where(CatalogStandardAsset.id == catalog_standard_id)
        )
    ).scalar_one_or_none()
    family = resolve_family_code(
        standard_code=asset.standard_code if asset else "",
        title=(asset.title_fa or asset.title or "") if asset else "",
        original_name=(asset.original_name or "") if asset else "",
        explicit=asset.family_code if asset else None,
    )
    if asset and asset.family_code != family:
        asset.family_code = family

    tender_map = map_clause_to_taxonomy(clause)
    tax_code = tender_map.get("taxonomy_code")
    slot = clause_slot_code(family, tax_code, clause_number) if tax_code else None

    std_clause = StandardClause(
        standard_id=catalog_standard_id,
        clause_number=clause_number,
        chapter=clause.get("chapter"),
        section=clause.get("section"),
        section_title=str(clause.get("title") or "").strip() or None,
        slot_code=slot,
        taxonomy_code=tax_code,
        taxonomy_confidence=tender_map.get("confidence"),
        raw_text=_clause_raw_text(clause),
        source_page=clause.get("source_page"),
    )
    session.add(std_clause)
    await session.flush()

    for item in requirements:
        session.add(
            Requirement(
                clause_id=std_clause.id,
                discipline=discipline,
                topic=list(taxonomy.get("topic") or []),
                element=list(taxonomy.get("element") or []),
                material=list(taxonomy.get("material") or []),
                subtopic=None,
                requirement_type=_requirement_type_from_dict(item),
                requirement_text=str(item.get("requirement_text") or "").strip(),
                min_value=item.get("min_value"),
                max_value=item.get("max_value"),
                unit=item.get("unit"),
                conditions_text=item.get("conditions_text"),
            )
        )

    await session.commit()
    return std_clause.id


async def persist_sample_pipeline(path: str | None = None, *, force_reingest: bool = False) -> None:
    """Parse sample file, classify/extract via LLM, and persist clauses + requirements."""
    await init_db()
    sample = path or str(_default_sample_path())
    raw = Path(sample).read_text(encoding="utf-8")
    clauses = parse_sample_file(sample)
    file_meta = parse_catalog_file_metadata(raw)
    print(f"Parsed {len(clauses)} clause(s) from {sample}")

    async with SessionLocal() as session:
        catalog_id = await get_or_create_catalog_standard(
            session,
            standard_code="CODE55-VOL1-IR",
            country_code=file_meta.country_code or "IR",
            title_fa=file_meta.title_fa
            or "ضابطه شماره ۵۵ - مشخصات فنی عمومی کارهای ساختمانی (بازنگری سوم) - جلد اول",
            publisher=file_meta.publisher or "سازمان برنامه و بودجه کشور",
            standard_class="technical",
        )
        asset = (
            await session.execute(
                select(CatalogStandardAsset).where(CatalogStandardAsset.id == catalog_id)
            )
        ).scalar_one()
        await _apply_catalog_metadata_from_text(session, asset, raw)
        if file_meta.volume and not asset.standard_version:
            asset.standard_version = file_meta.volume
            await session.commit()
        print(f"Using catalog_standard_assets.id={catalog_id}\n")

        saved_clauses, saved_requirements, skipped = await _persist_clauses_loop(
            session,
            catalog_id=catalog_id,
            standard_code="CODE55-VOL1-IR",
            clauses=clauses,
            skip_existing=not force_reingest,
        )

    print(
        f"\nDone: saved {saved_clauses} clause(s), "
        f"{saved_requirements} requirement(s), skipped {skipped}."
    )


def _load_text_from_path(path: str) -> str:
    """Load UTF-8 text or extract from .docx/.pdf for local ingest."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".docx", ".pdf"}:
        from app.services.extractor import extract_document_full

        return (extract_document_full(p, allow_ocr=False).merged_text or "").strip()
    return p.read_text(encoding="utf-8")


async def persist_catalog_pipeline(
    standard_code: str,
    *,
    section_prefix: str | None = None,
    text_path: str | None = None,
    force_reingest: bool = False,
) -> None:
    """Ingest from catalog PDF text (or optional UTF-8 file) → clauses → DB."""
    from app.db_connect import ensure_db_reachable, is_transient_db_error

    try:
        await ensure_db_reachable()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot reach database: {exc}")
        from app.db_connect import db_host_port, dns_fix_hint

        host, _ = db_host_port()
        print(dns_fix_hint(host))
        return

    await init_db()
    code = standard_code.strip()

    async with SessionLocal() as session:
        asset = None
        try:
            asset = (
                await session.execute(
                    select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == code)
                )
            ).scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001
            if is_transient_db_error(exc):
                print(f"Database query failed (transient): {exc}")
                print("Retry when DNS is stable, or run scripts/fix_supabase_hosts.ps1 as Admin.")
            raise

        clauses: list[dict[str, Any]] = []
        source = ""
        raw = ""

        if text_path:
            raw = _load_text_from_path(text_path)
            clauses = parse_standards_text(raw, mode="auto", section_prefix=section_prefix)
            source = text_path
            if asset is not None:
                await _apply_catalog_metadata_from_text(session, asset, raw)
                if raw:
                    asset.extracted_text = raw[:500_000]
                    asset.extraction_status = "done"
                    await session.commit()
        elif asset is not None:
            from app.services.catalog_standard_text import ensure_catalog_standard_text

            raw = await ensure_catalog_standard_text(
                session, asset, force_refresh=force_reingest
            )

            pages: list = []
            try:
                pdf_path = await file_storage.open_for_read(asset.stored_path)
                if Path(pdf_path).exists() and Path(pdf_path).suffix.lower() == ".pdf":
                    extract_result = extract_catalog_standard_pages(Path(pdf_path))
                    pages = extract_result.pages
                    if pages and not raw:
                        raw = extract_result.merged_text
                        asset.extracted_text = raw[:500_000] or None
                        asset.extraction_status = "done" if raw else "empty"
                        await session.commit()
                        await session.refresh(asset)
            except Exception as exc:  # noqa: BLE001
                print(f"PDF page extract warning: {exc}")

            if raw:
                await _apply_catalog_metadata_from_text(session, asset, raw)

            if pages:
                clauses = parse_standards_pages(
                    pages, mode="auto", section_prefix=section_prefix
                )
                source = f"catalog:{code} (page-aware, {len(pages)} pages)"
            elif raw:
                clauses = parse_standards_text(raw, mode="auto", section_prefix=section_prefix)
                source = f"catalog:{code} (merged text, {len(raw)} chars)"
            else:
                clauses = []
                source = f"catalog:{code} (empty extract)"
        else:
            print(f"Catalog standard {code} not found and no --text file given.")
            return

        print(f"Parsed {len(clauses)} clause(s) from {source}")
        if not clauses:
            print("No clauses detected — try uploading PDF or use sample .txt with --text.")
            return

        before_filter = len(clauses)
        clauses = filter_substantive_clauses(clauses, min_chars=40)
        if before_filter != len(clauses):
            print(
                f"Filtered to {len(clauses)} substantive clause(s) "
                f"(dropped {before_filter - len(clauses)} TOC/short stubs)"
            )

        if asset is None:
            file_meta = parse_catalog_file_metadata(raw if text_path else "")
            catalog_id = await get_or_create_catalog_standard(
                session,
                standard_code=code,
                country_code=file_meta.country_code or "IR",
                title_fa=file_meta.title_fa or code,
                publisher=file_meta.publisher,
                standard_class="technical",
            )
        else:
            catalog_id = asset.id

        if force_reingest:
            cleared = await _clear_catalog_clauses(session, catalog_id)
            print(f"Force re-ingest: cleared {cleared} existing clause(s).\n")

        print(f"Using catalog_standard_assets.id={catalog_id}\n")
        saved_clauses, saved_requirements, skipped = await _persist_clauses_loop(
            session,
            catalog_id=catalog_id,
            standard_code=code,
            clauses=clauses,
            skip_existing=not force_reingest,
        )

    print(
        f"\nDone: saved {saved_clauses} clause(s), "
        f"{saved_requirements} requirement(s), skipped {skipped}."
    )


async def demo_tender_gap_check(
    *,
    standard_code: str,
    tender_path: str,
) -> None:
    """Demo: flag standard requirements not clearly covered in a tender text file."""
    tender_text = Path(tender_path).read_text(encoding="utf-8")

    async with SessionLocal() as session:
        code, requirements = await load_requirements_for_standard(session, standard_code=standard_code)

    if not requirements:
        print(f"No requirements in DB for {code}. Run --save or --save-catalog first.")
        return

    gaps = check_standard_coverage(requirements, tender_text, standard_code=code)
    print(f"Checked {len(requirements)} requirement(s); found {len(gaps)} gap(s).\n")
    for g in gaps:
        print(json.dumps(
            {
                "clause": g.clause_number,
                "gap_type": g.gap_type,
                "severity": g.severity,
                "message_en": g.message_en,
                "requirement": g.requirement_text[:200],
            },
            ensure_ascii=False,
            indent=2,
        ))
        print()


def _cli_arg(flag: str, argv: list[str]) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        return None
    return argv[idx + 1]


def run_sample_pipeline(path: str | None = None) -> None:
    """Demo: parse sample file, classify taxonomy + extract requirements per clause."""
    sample = path or str(_default_sample_path())
    clauses = parse_sample_file(sample)
    print(f"Parsed {len(clauses)} clause(s) from {sample}\n")
    for clause in clauses:
        print("=" * 60)
        taxonomy = classify_clause(clause)
        requirements = extract_requirements(clause)
        result = {
            "clause_number": clause.get("clause_number"),
            "title": clause.get("title"),
            "taxonomy": taxonomy,
            "requirements": requirements,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()


def _configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    _configure_stdio_utf8()
    argv = sys.argv[1:]
    if "--save-catalog" in argv:
        code = _cli_arg("--save-catalog", argv) or "CODE55-VOL1-IR"
        section = _cli_arg("--section", argv)
        text = _cli_arg("--text", argv)
        force = "--force" in argv
        asyncio.run(
            persist_catalog_pipeline(
                code,
                section_prefix=section,
                text_path=text,
                force_reingest=force,
            )
        )
    elif "--check-gaps" in argv:
        code = _cli_arg("--standard", argv) or "CODE55-VOL1-IR"
        tender = _cli_arg("--tender", argv)
        if not tender:
            print("Usage: --check-gaps --standard CODE --tender path/to/tender.txt")
            sys.exit(1)
        asyncio.run(demo_tender_gap_check(standard_code=code, tender_path=tender))
    elif "--save" in argv:
        path = _cli_arg("--text", argv)
        force = "--force" in argv
        asyncio.run(persist_sample_pipeline(path, force_reingest=force))
    else:
        path = _cli_arg("--text", argv)
        run_sample_pipeline(path)
