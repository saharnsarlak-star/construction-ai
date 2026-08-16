"""Build taxonomy-grouped standard sections with stable slot codes."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogStandardAsset, ProjectStandard
from app.services.catalog_standard_text import ensure_catalog_standard_text
from app.standards_engine.ingestion.clause_parser import _is_toc_stub, parse_standards_text
from app.standards_engine.models import StandardClause
from app.tender_taxonomy.catalog import get_entry
from app.tender_taxonomy.standard_codes import (
    clause_slot_code,
    color_index_for_taxonomy,
    resolve_family_code,
    section_slot_code,
    taxonomy_parts,
    taxonomy_subcode,
)
from app.tender_taxonomy.standard_mapper import map_clauses_to_taxonomy

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r"^\d+(?:-\d+)+$")
_TOC_TRAIL_RE = re.compile(r"\.{3,}\s*\d+\s*$")

_SECTIONS_CACHE: dict[str, tuple[str, dict[str, Any]]] = {}


def _clause_title(clause: dict[str, Any]) -> str:
    title = str(clause.get("title") or "").strip()
    if title:
        return title
    body = str(clause.get("raw_text") or clause.get("text") or "").strip()
    return body[:160]


def _clause_body(clause: dict[str, Any]) -> str:
    return str(clause.get("raw_text") or clause.get("text") or "").strip()


def _entry_labels(code: str | None) -> dict[str, str | None]:
    if not code:
        return {"title_fa": None, "title_en": None, "path_fa": None, "kind": None}
    entry = get_entry(code)
    if entry is None:
        return {"title_fa": None, "title_en": None, "path_fa": None, "kind": None}
    return {
        "title_fa": entry.title_fa,
        "title_en": entry.title_en,
        "path_fa": entry.path_fa,
        "kind": entry.kind,
    }


def _section_from_clause_number(clause_number: str) -> str:
    parts = [p for p in (clause_number or "").split("-") if p]
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    if parts:
        return parts[0]
    return "general"


def _clean_section(clause_number: str, section: str | None) -> str:
    sec = str(section or "").strip()
    if not _SECTION_RE.match(sec) or len(sec) > 32:
        return _section_from_clause_number(clause_number)
    return sec


def _clean_chapter(clause_number: str, chapter: str | None) -> str | None:
    parts = [p for p in (clause_number or "").split("-") if p and p.isdigit()]
    if parts:
        return parts[0][:32]
    ch = str(chapter or "").strip()
    if ch.isdigit() and len(ch) <= 4:
        return ch[:32]
    return None


def _clean_title(title: str | None, *, max_len: int = 512) -> str | None:
    text = str(title or "").strip()
    if not text:
        return None
    text = _TOC_TRAIL_RE.sub("", text).strip()
    return text[:max_len] or None


def _sort_code(code: str) -> list[Any]:
    return [int(p) if p.isdigit() else p for p in (code or "").split(".")]


def _cache_key(asset: CatalogStandardAsset) -> str:
    text_len = len((asset.extracted_text or "").strip())
    raw = f"{asset.id}|{asset.standard_code}|{asset.standard_version}|{asset.size_bytes}|{text_len}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def build_taxonomy_tree_from_mapped_clauses(
    *,
    family_code: str,
    mapped_clauses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Nest standard chapters under taxonomy category > subcategory > topic."""
    categories: dict[str, dict[str, Any]] = {}

    def ensure_chapter(node: dict[str, Any], section: str) -> dict[str, Any]:
        chapters = node.setdefault("chapters", {})
        tax_key = node["code"]
        return chapters.setdefault(
            section,
            {
                "section": section,
                "slot_code": section_slot_code(family_code, taxonomy_subcode(tax_key), section),
                "clauses": [],
            },
        )

    for row in mapped_clauses:
        tax_code = str(row.get("taxonomy_code") or "").strip()
        if not tax_code:
            continue

        cat_code, sub_code, topic_code = taxonomy_parts(tax_code)
        if not cat_code:
            continue

        cat = categories.setdefault(
            cat_code,
            {
                "code": cat_code,
                "kind": "category",
                "color_index": color_index_for_taxonomy(tax_code),
                **_entry_labels(cat_code),
                "subcategories": {},
                "topics": {},
                "clause_count": 0,
            },
        )

        if topic_code and sub_code:
            sub = cat["subcategories"].setdefault(
                sub_code,
                {
                    "code": sub_code,
                    "kind": "subcategory",
                    **_entry_labels(sub_code),
                    "topics": {},
                    "clause_count": 0,
                },
            )
            node = sub["topics"].setdefault(
                topic_code,
                {
                    "code": topic_code,
                    "kind": "topic",
                    "slot_prefix": f"{family_code}::{topic_code}",
                    **_entry_labels(topic_code),
                    "chapters": {},
                    "clause_count": 0,
                },
            )
            sub["clause_count"] += 1
        elif sub_code:
            node = cat["subcategories"].setdefault(
                sub_code,
                {
                    "code": sub_code,
                    "kind": "subcategory",
                    "slot_prefix": f"{family_code}::{sub_code}",
                    **_entry_labels(sub_code),
                    "chapters": {},
                    "clause_count": 0,
                },
            )
        else:
            node = cat

        section = _clean_section(str(row.get("clause_number") or ""), row.get("section") or row.get("chapter"))

        chapter = ensure_chapter(node, section)
        clause_number = str(row.get("clause_number") or "").strip()
        chapter["clauses"].append(
            {
                "clause_number": clause_number,
                "title": row.get("title") or _clause_title(row),
                "text_preview": (row.get("text_preview") or _clause_body(row))[:240],
                "source_page": row.get("source_page"),
                "taxonomy_code": tax_code,
                "taxonomy_confidence": row.get("confidence"),
                "slot_code": row.get("slot_code")
                or clause_slot_code(family_code, tax_code, clause_number),
                **_entry_labels(tax_code),
            }
        )
        if node is not cat:
            node["clause_count"] = node.get("clause_count", 0) + 1
        cat["clause_count"] += 1

    ordered: list[dict[str, Any]] = []
    for cat_code in sorted(categories.keys(), key=_sort_code):
        cat = categories[cat_code]
        subcategories = []
        for sub_code in sorted(cat["subcategories"].keys(), key=_sort_code):
            sub = cat["subcategories"][sub_code]
            if sub.get("topics"):
                topics = []
                for topic_code in sorted(sub["topics"].keys(), key=_sort_code):
                    topic = sub["topics"][topic_code]
                    topic["chapters"] = sorted(
                        topic.pop("chapters", {}).values(),
                        key=lambda c: c.get("section") or "",
                    )
                    topics.append(topic)
                sub["topics"] = topics
            else:
                sub["chapters"] = sorted(
                    sub.pop("chapters", {}).values(),
                    key=lambda c: c.get("section") or "",
                )
            subcategories.append(sub)
        cat["subcategories"] = subcategories

        direct_topics = []
        for topic_code in sorted(cat.get("topics", {}).keys(), key=_sort_code):
            topic = cat["topics"][topic_code]
            topic["chapters"] = sorted(
                topic.pop("chapters", {}).values(),
                key=lambda c: c.get("section") or "",
            )
            direct_topics.append(topic)
        cat["topics"] = direct_topics
        ordered.append(cat)

    return ordered


def _compute_live_mapping(
    text: str,
    *,
    family_code: str,
    section_prefix: str | None,
) -> list[dict[str, Any]]:
    clauses = parse_standards_text(text, mode="auto", section_prefix=section_prefix)
    return map_clauses_to_taxonomy(clauses, family_code=family_code)


async def _load_clauses_from_db(
    session: AsyncSession,
    *,
    standard_id: int,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(StandardClause)
            .where(StandardClause.standard_id == standard_id)
            .order_by(StandardClause.clause_number)
        )
    ).scalars().all()

    if not rows:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not row.taxonomy_code:
            continue
        out.append(
            {
                "clause_number": row.clause_number,
                "section": row.section,
                "chapter": row.chapter,
                "title": row.section_title or row.raw_text[:160],
                "text_preview": row.raw_text[:240],
                "source_page": row.source_page,
                "taxonomy_code": row.taxonomy_code,
                "confidence": row.taxonomy_confidence,
                "slot_code": row.slot_code,
            }
        )
    return out


async def _db_clause_count(session: AsyncSession, standard_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count(StandardClause.id)).where(
                    StandardClause.standard_id == standard_id,
                    StandardClause.taxonomy_code.is_not(None),
                )
            )
        ).scalar_one()
        or 0
    )


def _build_payload(
    *,
    asset: CatalogStandardAsset,
    family: str,
    mapped_clauses: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    categories = build_taxonomy_tree_from_mapped_clauses(
        family_code=family,
        mapped_clauses=mapped_clauses,
    )
    clause_count = sum(c.get("clause_count") or 0 for c in categories)
    topic_count = sum(
        len(sub.get("topics") or [])
        for cat in categories
        for sub in (cat.get("subcategories") or [])
    ) + sum(len(cat.get("topics") or []) for cat in categories)
    return {
        "family_code": family,
        "standard_code": asset.standard_code,
        "standard_version": asset.standard_version,
        "title_fa": asset.title_fa or asset.title,
        "title_en": asset.title_en or asset.title,
        "source": source,
        "category_count": len(categories),
        "topic_count": topic_count,
        "clause_count": clause_count,
        "categories": categories,
    }


async def get_standard_sections(
    session: AsyncSession,
    *,
    standard_code: str,
    lang: str = "fa",
    section_prefix: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return taxonomy tree with standard chapters; fast path uses DB + memory cache."""
    _ = lang
    asset = (
        await session.execute(
            select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == standard_code)
        )
    ).scalar_one_or_none()
    if asset is None:
        return {"error": "not_found"}

    family = asset.family_code or resolve_family_code(
        standard_code=asset.standard_code,
        title=asset.title_fa or asset.title or "",
        original_name=asset.original_name or "",
    )
    if asset.family_code != family:
        asset.family_code = family
        await session.commit()

    cache_ver = _cache_key(asset)
    if not refresh and asset.standard_code in _SECTIONS_CACHE:
        cached_ver, cached = _SECTIONS_CACHE[asset.standard_code]
        if cached_ver == cache_ver:
            return cached

    db_count = await _db_clause_count(session, standard_id=asset.id)
    mapped: list[dict[str, Any]] = []
    source = "database"

    if db_count > 0 and not refresh:
        mapped = await _load_clauses_from_db(session, standard_id=asset.id)
    else:
        text = await ensure_catalog_standard_text(session, asset)
        if len(text) < 40:
            if db_count > 0:
                mapped = await _load_clauses_from_db(session, standard_id=asset.id)
            else:
                return {
                    "error": "no_text",
                    "family_code": family,
                    "standard_code": asset.standard_code,
                }
        else:
            source = "live"
            mapped = await asyncio.to_thread(
                _compute_live_mapping,
                text,
                family_code=family,
                section_prefix=section_prefix,
            )
            payload = _build_payload(
                asset=asset, family=family, mapped_clauses=mapped, source=source
            )
            _SECTIONS_CACHE[asset.standard_code] = (cache_ver, payload)
            try:
                await persist_taxonomy_mapped_clauses(
                    session,
                    asset=asset,
                    section_prefix=section_prefix,
                    force_replace=True,
                    precomputed=mapped,
                )
                payload["source"] = "database"
                _SECTIONS_CACHE[asset.standard_code] = (cache_ver, payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "persist_taxonomy_mapped_clauses failed for %s: %s",
                    asset.standard_code,
                    exc,
                )
                await session.rollback()
            return payload

    payload = _build_payload(asset=asset, family=family, mapped_clauses=mapped, source=source)
    _SECTIONS_CACHE[asset.standard_code] = (cache_ver, payload)
    return payload


async def persist_taxonomy_mapped_clauses(
    session: AsyncSession,
    *,
    asset: CatalogStandardAsset,
    section_prefix: str | None = None,
    force_replace: bool = False,
    precomputed: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Persist taxonomy-mapped clauses (no LLM requirements) for edition replacement."""
    from sqlalchemy import delete

    family = asset.family_code or resolve_family_code(
        standard_code=asset.standard_code,
        title=asset.title_fa or asset.title or "",
        original_name=asset.original_name or "",
    )
    asset.family_code = family

    if precomputed is None:
        text = await ensure_catalog_standard_text(session, asset)
        if len(text) < 40:
            return {"saved": 0, "skipped": 0, "deleted": 0}
        mapped = await asyncio.to_thread(
            _compute_live_mapping,
            text,
            family_code=family,
            section_prefix=section_prefix,
        )
    else:
        mapped = precomputed

    if force_replace:
        result = await session.execute(
            delete(StandardClause).where(StandardClause.standard_id == asset.id)
        )
        deleted = int(result.rowcount or 0)
    else:
        deleted = 0

    saved = 0
    skipped = 0
    for row in mapped:
        tax_code = row.get("taxonomy_code")
        clause_number = str(row.get("clause_number") or "").strip()
        if not tax_code or not clause_number:
            skipped += 1
            continue

        slot = row.get("slot_code") or clause_slot_code(family, tax_code, clause_number)
        body = str(row.get("text_preview") or row.get("title") or _clause_body(row)).strip()
        body = _TOC_TRAIL_RE.sub("", body).strip()
        if len(body) < 8:
            skipped += 1
            continue
        if _is_toc_stub({"title": row.get("title"), "raw_text": body}):
            skipped += 1
            continue

        section = _clean_section(clause_number, row.get("section") or row.get("chapter"))
        chapter = _clean_chapter(clause_number, row.get("chapter"))
        title = _clean_title(str(row.get("title") or ""))

        session.add(
            StandardClause(
                standard_id=asset.id,
                clause_number=clause_number[:64],
                chapter=chapter,
                section=section[:64],
                section_title=title,
                slot_code=slot[:160],
                taxonomy_code=tax_code[:32],
                taxonomy_confidence=row.get("confidence"),
                raw_text=body[:8000],
                source_page=row.get("source_page"),
            )
        )
        saved += 1

    await session.commit()
    _SECTIONS_CACHE.pop(asset.standard_code, None)
    return {"saved": saved, "skipped": skipped, "deleted": deleted}


async def warm_standard_sections_cache(session: AsyncSession, *, standard_code: str) -> None:
    """Background warm: persist mapping after text extraction completes."""
    try:
        asset = (
            await session.execute(
                select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == standard_code)
            )
        ).scalar_one_or_none()
        if asset is None:
            return
        count = await _db_clause_count(session, standard_id=asset.id)
        if count > 0:
            await get_standard_sections(session, standard_code=standard_code)
            return
        await persist_taxonomy_mapped_clauses(session, asset=asset, force_replace=True)
        await get_standard_sections(session, standard_code=standard_code)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("warm_standard_sections_cache failed %s", standard_code)


async def assert_project_standard_access(
    session: AsyncSession,
    *,
    project_id: int,
    standard_code: str,
) -> None:
    row = (
        await session.execute(
            select(ProjectStandard).where(
                ProjectStandard.project_id == project_id,
                ProjectStandard.standard_code == standard_code,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="Standard is not on this project's applicable/selected list",
        )
