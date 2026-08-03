"""Phase 2 ontology ingest: Party + Element Registry + OntologyEdge from CDM/extraction.

Additive only. Callers gate with settings.ontology_enabled.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, ElementDocumentRef, OntologyEdge, Party, ProjectElement
from app.services.ontology_predicates import is_known_predicate, normalize_predicate

logger = logging.getLogger(__name__)

# Marks / names that often identify the same physical object across docs
_MARK_PATTERNS = [
    re.compile(r"\b(?:type\s*mark|mark)\s*[:\-]?\s*([A-Z]{0,3}-?\d{1,4}[A-Z]?)\b", re.I),
    re.compile(r"\b(Wall-[A-Z0-9]+)\b", re.I),
    re.compile(r"\b(W-\d{1,3}[A-Z]?)\b", re.I),
    re.compile(r"\b(Slab-[A-Z0-9]+)\b", re.I),
    re.compile(r"\b(S-\d{1,3}[A-Z]?)\b", re.I),
]
_DRAWING_REF_PAT = re.compile(
    r"\b(?:drawing|dwg|sheet|plan)\s*[:\-]?\s*([A-Z]{1,3}-?\d{1,4}[A-Z]?)\b", re.I
)
_PARTY_PATTERNS = [
    (re.compile(r"\b(?:Employer|Client|Owner)\s*[:\-]\s*([^\n;,]{3,80})", re.I), "employer"),
    (re.compile(r"\b(?:Contractor|General\s+Contractor|GC)\s*[:\-]\s*([^\n;,]{3,80})", re.I), "contractor"),
    (re.compile(r"\b(?:Engineer|Consultant)\s*[:\-]\s*([^\n;,]{3,80})", re.I), "consultant"),
]


@dataclass
class ElementMention:
    element_type: str
    name_label: str | None = None
    type_mark: str | None = None
    ifc_global_id: str | None = None
    drawing_ref: str | None = None
    fire_rating: str | None = None
    host_level: str | None = None
    material_ref: str | None = None
    source_kind: str = "cdm_text"
    source_local_id: str = ""
    excerpt: str | None = None
    confidence: int = 70


def normalize_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def build_match_key(
    *,
    element_type: str,
    type_mark: str | None = None,
    name_label: str | None = None,
    drawing_ref: str | None = None,
    prefer_drawing: bool = False,
) -> str:
    """Deterministic project-local key when IFC GUID is unavailable (GAP-05)."""
    et = normalize_token(element_type) or "element"
    if et.startswith("ifc"):
        et = et[3:] or "element"
    mark = normalize_token(type_mark) or normalize_token(name_label)
    if not mark:
        mark = "unnamed"
    if prefer_drawing and drawing_ref:
        return f"{normalize_token(drawing_ref)}|{et}:{mark}"
    return f"{et}:{mark}"


async def upsert_party(
    db: AsyncSession,
    *,
    project_id: int,
    legal_name: str,
    party_role: str,
    contact_ref: str | None = None,
) -> Party:
    name = (legal_name or "").strip()
    role = (party_role or "unknown").strip().lower() or "unknown"
    existing = (
        await db.execute(
            select(Party).where(
                Party.project_id == project_id,
                Party.legal_name == name,
                Party.party_role == role,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if contact_ref and not existing.contact_ref:
            existing.contact_ref = contact_ref
        return existing
    party = Party(
        project_id=project_id,
        legal_name=name,
        party_role=role,
        contact_ref=contact_ref,
    )
    db.add(party)
    await db.flush()
    return party


async def upsert_ontology_edge(
    db: AsyncSession,
    *,
    project_id: int,
    from_type: str,
    from_id: str | int,
    to_type: str,
    to_id: str | int,
    predicate: str,
    confidence: int | None = None,
    origin_kind: str = "python",
    document_id: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> OntologyEdge | None:
    pred = normalize_predicate(predicate)
    if not pred:
        return None
    if not is_known_predicate(pred):
        # Allow unknown predicates for expandability, but log (GAP-11)
        logger.info("Ontology edge using non-catalog predicate: %s", pred)

    fid = str(from_id)
    tid = str(to_id)
    existing = (
        await db.execute(
            select(OntologyEdge).where(
                OntologyEdge.project_id == project_id,
                OntologyEdge.from_type == from_type,
                OntologyEdge.from_id == fid,
                OntologyEdge.to_type == to_type,
                OntologyEdge.to_id == tid,
                OntologyEdge.predicate == pred,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    edge = OntologyEdge(
        project_id=project_id,
        from_type=from_type,
        from_id=fid,
        to_type=to_type,
        to_id=tid,
        predicate=pred,
        confidence=confidence,
        origin_kind=origin_kind,
        document_id=document_id,
        evidence_json=json.dumps(evidence, ensure_ascii=False) if evidence else None,
    )
    db.add(edge)
    await db.flush()
    return edge


async def resolve_or_create_element(
    db: AsyncSession,
    *,
    project_id: int,
    mention: ElementMention,
) -> ProjectElement:
    """GAP-05 merge: IFC GUID first, then match_key (type + mark)."""
    match_key = build_match_key(
        element_type=mention.element_type,
        type_mark=mention.type_mark,
        name_label=mention.name_label,
        drawing_ref=mention.drawing_ref,
        prefer_drawing=False,
    )

    element: ProjectElement | None = None
    if mention.ifc_global_id:
        element = (
            await db.execute(
                select(ProjectElement).where(
                    ProjectElement.project_id == project_id,
                    ProjectElement.ifc_global_id == mention.ifc_global_id,
                )
            )
        ).scalar_one_or_none()

    if element is None:
        element = (
            await db.execute(
                select(ProjectElement).where(
                    ProjectElement.project_id == project_id,
                    ProjectElement.match_key == match_key,
                )
            )
        ).scalar_one_or_none()

    if element is None and mention.type_mark:
        # Secondary: same type_mark under any match_key for this project
        element = (
            await db.execute(
                select(ProjectElement).where(
                    ProjectElement.project_id == project_id,
                    ProjectElement.type_mark == mention.type_mark,
                )
            )
        ).scalar_one_or_none()

    if element is None and mention.name_label:
        element = (
            await db.execute(
                select(ProjectElement).where(
                    ProjectElement.project_id == project_id,
                    ProjectElement.name_label == mention.name_label,
                )
            )
        ).scalar_one_or_none()

    if element is None:
        element = ProjectElement(
            project_id=project_id,
            element_type=_normalize_element_type(mention.element_type),
            name_label=mention.name_label,
            type_mark=mention.type_mark or mention.name_label,
            ifc_global_id=mention.ifc_global_id,
            match_key=match_key,
            fire_rating=mention.fire_rating,
            host_level=mention.host_level,
            material_ref=mention.material_ref,
            drawing_ref=mention.drawing_ref,
            confidence=mention.confidence,
        )
        db.add(element)
        await db.flush()
        return element

    # Merge enrichments onto existing registry row
    if mention.ifc_global_id and not element.ifc_global_id:
        element.ifc_global_id = mention.ifc_global_id
    if mention.name_label and not element.name_label:
        element.name_label = mention.name_label
    if mention.type_mark and not element.type_mark:
        element.type_mark = mention.type_mark
    if mention.fire_rating and not element.fire_rating:
        element.fire_rating = mention.fire_rating
    if mention.host_level and not element.host_level:
        element.host_level = mention.host_level
    if mention.drawing_ref and not element.drawing_ref:
        element.drawing_ref = mention.drawing_ref
    if mention.material_ref and not element.material_ref:
        element.material_ref = mention.material_ref
    if mention.confidence and (element.confidence is None or mention.confidence > element.confidence):
        element.confidence = mention.confidence
    await db.flush()
    return element


async def attach_document_ref(
    db: AsyncSession,
    *,
    project_id: int,
    element: ProjectElement,
    document_id: int,
    mention: ElementMention,
) -> ElementDocumentRef:
    local_id = mention.source_local_id or ""
    existing = (
        await db.execute(
            select(ElementDocumentRef).where(
                ElementDocumentRef.element_id == element.id,
                ElementDocumentRef.document_id == document_id,
                ElementDocumentRef.source_kind == mention.source_kind,
                ElementDocumentRef.source_local_id == local_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    ref = ElementDocumentRef(
        project_id=project_id,
        element_id=element.id,
        document_id=document_id,
        source_kind=mention.source_kind,
        source_local_id=local_id,
        excerpt=(mention.excerpt or "")[:2000] or None,
        confidence=mention.confidence,
    )
    db.add(ref)
    await db.flush()
    return ref


def collect_mentions_from_canonical(
    *,
    canonical: dict[str, Any] | None,
    extracted_text: str,
    meta: dict[str, Any] | None = None,
) -> list[ElementMention]:
    """Pull element candidates from IFC CDM, GAEB tables, and free text."""
    mentions: list[ElementMention] = []
    canonical = canonical or {}
    meta = meta or {}
    extraction = meta.get("extraction") if isinstance(meta.get("extraction"), dict) else {}
    structured = extraction.get("structured") if isinstance(extraction.get("structured"), dict) else {}

    # --- IFC property highlights (guid merge) ---
    qty = canonical.get("quantities_summary") if isinstance(canonical.get("quantities_summary"), dict) else {}
    highlights = qty.get("property_highlights") or structured.get("property_highlights") or []
    for i, h in enumerate(highlights):
        if not isinstance(h, dict):
            continue
        ifc_type = str(h.get("type") or "IfcElement")
        name = h.get("name")
        gid = h.get("global_id")
        props = h.get("properties") if isinstance(h.get("properties"), dict) else {}
        fire = None
        for pset in props.values():
            if isinstance(pset, dict) and pset.get("FireRating"):
                fire = str(pset["FireRating"])
        mentions.append(
            ElementMention(
                element_type=_normalize_element_type(ifc_type),
                name_label=str(name) if name else None,
                type_mark=str(name) if name else None,
                ifc_global_id=str(gid) if gid else None,
                fire_rating=fire,
                source_kind="ifc_element",
                source_local_id=str(gid or f"hl-{i}"),
                excerpt=json.dumps(h, ensure_ascii=False)[:500],
                confidence=96,
            )
        )

    # --- GAEB / table rows ---
    for table in canonical.get("tables") or []:
        if not isinstance(table, dict):
            continue
        headers = [str(h).lower() for h in (table.get("headers") or [])]
        desc_idx = next((i for i, h in enumerate(headers) if "desc" in h), 1 if len(headers) > 1 else 0)
        code_idx = next((i for i, h in enumerate(headers) if h in {"code", "oz", "pos"}), 0)
        for r_i, row in enumerate(table.get("rows") or []):
            if not isinstance(row, list) or not row:
                continue
            desc = str(row[desc_idx] if desc_idx < len(row) else row[-1])
            code = str(row[code_idx] if code_idx < len(row) else "")
            for m in _mentions_from_text(
                desc,
                source_kind="boq_item",
                source_local_id=code or f"row-{r_i}",
                confidence=90,
            ):
                mentions.append(m)

    # --- Free text / content units (contract, drawings labels) ---
    texts = [extracted_text or ""]
    for cu in canonical.get("content_units") or []:
        if isinstance(cu, dict) and cu.get("text"):
            texts.append(str(cu["text"]))
    blob = "\n".join(texts)
    source_kind = "contract_clause" if _looks_like_contract(blob) else "cdm_text"
    mentions.extend(_mentions_from_text(blob, source_kind=source_kind, source_local_id="body", confidence=75))

    return _dedupe_mentions(mentions)


def collect_parties_from_text(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for pat, role in _PARTY_PATTERNS:
        for m in pat.finditer(text or ""):
            name = m.group(1).strip().strip(".")
            if len(name) >= 3:
                found.append((name, role))
    return found


async def ingest_document_ontology(
    db: AsyncSession,
    *,
    document: Document,
    canonical: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Main Phase 2 entry: upsert parties, merge elements, write references edges."""
    project_id = document.project_id
    doc_id = document.id
    text = document.extracted_text or ""

    if canonical is None or meta is None:
        try:
            meta_obj = json.loads(document.meta_json or "{}")
        except json.JSONDecodeError:
            meta_obj = {}
        meta = meta if meta is not None else meta_obj
        if canonical is None:
            canonical = meta_obj.get("canonical") if isinstance(meta_obj.get("canonical"), dict) else {}

    parties_created: list[int] = []
    for legal_name, role in collect_parties_from_text(text):
        party = await upsert_party(db, project_id=project_id, legal_name=legal_name, party_role=role)
        parties_created.append(party.id)
        await upsert_ontology_edge(
            db,
            project_id=project_id,
            from_type="Document",
            from_id=doc_id,
            to_type="Party",
            to_id=party.id,
            predicate="references",
            confidence=80,
            origin_kind="python",
            document_id=doc_id,
            evidence={"excerpt": legal_name, "role": role},
        )
        if role in {"employer", "contractor", "consultant", "engineer"}:
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="Document",
                from_id=doc_id,
                to_type="Party",
                to_id=party.id,
                predicate="allocates_responsibility",
                confidence=70,
                origin_kind="python",
                document_id=doc_id,
            )

    mentions = collect_mentions_from_canonical(
        canonical=canonical or {},
        extracted_text=text,
        meta=meta or {},
    )
    element_ids: list[int] = []
    for mention in mentions:
        element = await resolve_or_create_element(db, project_id=project_id, mention=mention)
        await attach_document_ref(
            db,
            project_id=project_id,
            element=element,
            document_id=doc_id,
            mention=mention,
        )
        element_ids.append(element.id)
        await upsert_ontology_edge(
            db,
            project_id=project_id,
            from_type="Document",
            from_id=doc_id,
            to_type="ProjectElement",
            to_id=element.id,
            predicate="references",
            confidence=mention.confidence,
            origin_kind="python",
            document_id=doc_id,
            evidence={
                "source_kind": mention.source_kind,
                "source_local_id": mention.source_local_id,
                "match_key": element.match_key,
                "ifc_global_id": element.ifc_global_id,
            },
        )
        # BOQ item quantifies the physical element
        if mention.source_kind == "boq_item":
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="BoqItem",
                from_id=mention.source_local_id or f"doc{doc_id}",
                to_type="ProjectElement",
                to_id=element.id,
                predicate="quantifies",
                confidence=mention.confidence,
                origin_kind="python",
                document_id=doc_id,
            )

    return {
        "parties": parties_created,
        "elements": list(dict.fromkeys(element_ids)),
        "mention_count": len(mentions),
    }


def element_to_dict(element: ProjectElement, refs: list[ElementDocumentRef] | None = None) -> dict[str, Any]:
    return {
        "id": element.id,
        "project_id": element.project_id,
        "element_type": element.element_type,
        "name_label": element.name_label,
        "type_mark": element.type_mark,
        "ifc_global_id": element.ifc_global_id,
        "match_key": element.match_key,
        "fire_rating": element.fire_rating,
        "host_level": element.host_level,
        "drawing_ref": element.drawing_ref,
        "confidence": element.confidence,
        "document_refs": [
            {
                "id": r.id,
                "document_id": r.document_id,
                "source_kind": r.source_kind,
                "source_local_id": r.source_local_id,
                "excerpt": (r.excerpt or "")[:300],
                "confidence": r.confidence,
            }
            for r in (refs or list(element.document_refs or []))
        ],
    }


# ----- helpers -----


def _normalize_element_type(raw: str) -> str:
    t = (raw or "element").strip()
    if t.lower().startswith("ifc"):
        # IfcWall → Wall
        rest = t[3:]
        return rest or t
    return t


def _looks_like_contract(text: str) -> bool:
    sample = (text or "")[:4000].lower()
    hits = sum(
        1
        for k in ("shall", "employer", "contractor", "clause", "agreement", "contract")
        if k in sample
    )
    return hits >= 2


def _mentions_from_text(
    text: str,
    *,
    source_kind: str,
    source_local_id: str,
    confidence: int,
) -> list[ElementMention]:
    if not text:
        return []
    drawing_refs = [m.group(1) for m in _DRAWING_REF_PAT.finditer(text)]
    drawing_ref = drawing_refs[0] if drawing_refs else None
    out: list[ElementMention] = []
    seen: set[str] = set()
    for pat in _MARK_PATTERNS:
        for m in pat.finditer(text):
            mark = m.group(1).strip()
            key = mark.lower()
            if key in seen:
                continue
            seen.add(key)
            et = "Wall" if mark.lower().startswith(("wall", "w-")) else (
                "Slab" if mark.lower().startswith(("slab", "s-")) else "element"
            )
            # Prefer exterior wall language if present near mark
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            excerpt = text[start:end].replace("\n", " ").strip()
            out.append(
                ElementMention(
                    element_type=et,
                    name_label=mark,
                    type_mark=mark,
                    drawing_ref=drawing_ref,
                    source_kind=source_kind,
                    source_local_id=source_local_id,
                    excerpt=excerpt[:400],
                    confidence=confidence,
                )
            )
    # Phrase without mark: "exterior wall" + drawing ref → synthetic mark from drawing
    if not out and drawing_ref and re.search(r"\bexterior\s+wall\b", text, re.I):
        out.append(
            ElementMention(
                element_type="Wall",
                name_label="Exterior Wall",
                type_mark=None,
                drawing_ref=drawing_ref,
                source_kind=source_kind,
                source_local_id=source_local_id,
                excerpt=f"exterior wall drawing {drawing_ref}",
                confidence=max(50, confidence - 15),
            )
        )
    return out


def _dedupe_mentions(mentions: list[ElementMention]) -> list[ElementMention]:
    best: dict[str, ElementMention] = {}
    for m in mentions:
        key = (
            m.ifc_global_id
            or build_match_key(
                element_type=m.element_type,
                type_mark=m.type_mark,
                name_label=m.name_label,
            )
        )
        # Prefer IFC / higher confidence
        prev = best.get(key)
        if prev is None or (m.ifc_global_id and not prev.ifc_global_id) or m.confidence > prev.confidence:
            best[key] = m
    return list(best.values())
