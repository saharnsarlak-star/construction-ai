"""Phase 5 — Knowledge Graph traversal for cross-document risk chains.

Walks OntologyEdge + Element Registry (Phase 2) to connect Findings that share
the same real-world ProjectElement. Additive only; gated by KNOWLEDGE_GRAPH_ENABLED.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Analysis,
    Document,
    ElementDocumentRef,
    Finding,
    OntologyEdge,
    ProjectElement,
)
from app.services.ontology_writer import upsert_ontology_edge

logger = logging.getLogger(__name__)

_MARK_RE = re.compile(
    r"\b(Wall-[A-Z0-9]+|W-\d{1,3}[A-Z]?|Slab-[A-Z0-9]+|S-\d{1,3}[A-Z]?)\b",
    re.I,
)
_DOC_NAME_RE = re.compile(
    r"\(([^)]+\.(?:txt|pdf|docx|xlsx|ifc|x83|X83|csv))\)|"
    r"(?:document|file|doc)\s*[=:]\s*([^\s,;]+)|"
    r"\b([A-Za-z0-9_\-]+\.(?:txt|pdf|docx|xlsx|ifc|x83|X83))\b",
    re.I,
)


async def link_findings_into_graph(
    db: AsyncSession,
    *,
    project_id: int,
    analysis_id: int,
    documents: list[Document] | None = None,
) -> dict[str, Any]:
    """
    Upsert OntologyEdges from Findings → Documents / ProjectElements.
    Does not alter Finding rows.
    """
    findings = (
        await db.execute(select(Finding).where(Finding.analysis_id == analysis_id))
    ).scalars().all()
    if not findings:
        return {"linked_findings": 0, "edges_added": 0}

    if documents is None:
        documents = (
            await db.execute(select(Document).where(Document.project_id == project_id))
        ).scalars().all()
    docs_by_id = {d.id: d for d in documents}
    docs_by_name = {(d.original_name or "").lower(): d for d in documents}

    elements = (
        await db.execute(select(ProjectElement).where(ProjectElement.project_id == project_id))
    ).scalars().all()
    refs = (
        await db.execute(
            select(ElementDocumentRef).where(ElementDocumentRef.project_id == project_id)
        )
    ).scalars().all()
    refs_by_element: dict[int, list[ElementDocumentRef]] = defaultdict(list)
    elements_by_doc: dict[int, set[int]] = defaultdict(set)
    for r in refs:
        refs_by_element[r.element_id].append(r)
        elements_by_doc[r.document_id].add(r.element_id)

    edges_before = (
        await db.execute(
            select(OntologyEdge).where(OntologyEdge.project_id == project_id)
        )
    ).scalars().all()
    before_ids = {e.id for e in edges_before}

    linked = 0
    for finding in findings:
        blob = " ".join(
            filter(
                None,
                [
                    finding.title,
                    finding.description,
                    finding.evidence,
                    finding.source_excerpt,
                    finding.cause_effect_json,
                ],
            )
        )
        doc_ids = _resolve_document_ids(blob, docs_by_id, docs_by_name)
        element_ids = _resolve_element_ids(blob, elements, doc_ids, elements_by_doc)

        for did in doc_ids:
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="Finding",
                from_id=finding.id,
                to_type="Document",
                to_id=did,
                predicate="evidences",
                confidence=80,
                origin_kind="python",
                document_id=did,
                evidence={"finding_code": finding.code, "analysis_id": analysis_id},
            )
            # reverse convenience edge for traversal
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="Document",
                from_id=did,
                to_type="Finding",
                to_id=finding.id,
                predicate="evidences",
                confidence=80,
                origin_kind="python",
                document_id=did,
                evidence={"finding_code": finding.code, "analysis_id": analysis_id},
            )
            # inherit element links from document
            for eid in elements_by_doc.get(did, set()):
                element_ids.add(eid)

        for eid in element_ids:
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="Finding",
                from_id=finding.id,
                to_type="ProjectElement",
                to_id=eid,
                predicate="affects",
                confidence=85,
                origin_kind="python",
                evidence={
                    "finding_code": finding.code,
                    "analysis_id": analysis_id,
                    "via": "element_registry",
                },
            )
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="ProjectElement",
                from_id=eid,
                to_type="Finding",
                to_id=finding.id,
                predicate="affects",
                confidence=85,
                origin_kind="python",
                evidence={"finding_code": finding.code, "analysis_id": analysis_id},
            )
        if doc_ids or element_ids:
            linked += 1

    await db.flush()
    edges_after = (
        await db.execute(
            select(OntologyEdge).where(OntologyEdge.project_id == project_id)
        )
    ).scalars().all()
    return {
        "linked_findings": linked,
        "edges_added": max(0, len(edges_after) - len(before_ids)),
        "finding_count": len(findings),
        "element_count": len(elements),
    }


async def build_related_findings_chains(
    db: AsyncSession,
    *,
    project_id: int,
    analysis_id: int,
    max_hops: int = 4,
) -> list[dict[str, Any]]:
    """
    For each Finding, walk OntologyEdge / Element Registry to other Findings
    sharing the same ProjectElement (or multi-hop path through Document).
    """
    findings = (
        await db.execute(select(Finding).where(Finding.analysis_id == analysis_id))
    ).scalars().all()
    if len(findings) < 2:
        return []

    finding_by_id = {f.id: f for f in findings}
    elements = (
        await db.execute(select(ProjectElement).where(ProjectElement.project_id == project_id))
    ).scalars().all()
    element_by_id = {e.id: e for e in elements}
    refs = (
        await db.execute(
            select(ElementDocumentRef).where(ElementDocumentRef.project_id == project_id)
        )
    ).scalars().all()
    docs = (
        await db.execute(select(Document).where(Document.project_id == project_id))
    ).scalars().all()
    doc_by_id = {d.id: d for d in docs}

    edges = (
        await db.execute(select(OntologyEdge).where(OntologyEdge.project_id == project_id))
    ).scalars().all()

    # adjacency: (type, id) -> list[(predicate, type, id, edge_id)]
    adj: dict[tuple[str, str], list[tuple[str, str, str, int]]] = defaultdict(list)
    for e in edges:
        adj[(e.from_type, e.from_id)].append((e.predicate, e.to_type, e.to_id, e.id))
        # undirected for chain discovery (store reverse with same predicate mark)
        adj[(e.to_type, e.to_id)].append((f"inv:{e.predicate}", e.from_type, e.from_id, e.id))

    # Finding -> elements via edges and via shared-doc registry
    finding_elements: dict[int, set[int]] = defaultdict(set)
    for f in findings:
        for pred, t_type, t_id, _ in adj.get(("Finding", str(f.id)), []):
            if t_type == "ProjectElement" and not pred.startswith("inv:"):
                try:
                    finding_elements[f.id].add(int(t_id))
                except ValueError:
                    pass

    # Element -> findings
    element_findings: dict[int, set[int]] = defaultdict(set)
    for fid, eids in finding_elements.items():
        for eid in eids:
            element_findings[eid].add(fid)

    # Also connect findings that share an element through Document refs even if
    # Finding→Element edge missing: Finding→Document→Element→Document→Finding
    for f in findings:
        for pred, t_type, t_id, _ in adj.get(("Finding", str(f.id)), []):
            if t_type != "Document" or pred.startswith("inv:"):
                continue
            try:
                did = int(t_id)
            except ValueError:
                continue
            for eid in {r.element_id for r in refs if r.document_id == did}:
                finding_elements[f.id].add(eid)
                element_findings[eid].add(f.id)

    chains: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int, int]] = set()  # anchor, related, element

    for eid, fids in element_findings.items():
        if len(fids) < 2:
            continue
        el = element_by_id.get(eid)
        if not el:
            continue
        ordered = sorted(fids)
        for anchor_id in ordered:
            related_ids = [x for x in ordered if x != anchor_id]
            if not related_ids:
                continue
            hops = []
            for rid in related_ids:
                key = (min(anchor_id, rid), max(anchor_id, rid), eid)
                if key in seen_pairs and anchor_id > rid:
                    continue
                seen_pairs.add(key)
                path = _shortest_path(
                    adj,
                    start=("Finding", str(anchor_id)),
                    goal=("Finding", str(rid)),
                    max_hops=max_hops,
                )
                if not path:
                    # Construct explicit element-mediated path
                    path = [
                        {"node": f"Finding:{anchor_id}", "predicate": None},
                        {"node": f"ProjectElement:{eid}", "predicate": "affects"},
                        {"node": f"Finding:{rid}", "predicate": "affects"},
                    ]
                rf = finding_by_id[rid]
                hops.append(
                    {
                        "finding_id": rid,
                        "code": rf.code,
                        "title": rf.title,
                        "severity": rf.severity.value if hasattr(rf.severity, "value") else str(rf.severity),
                        "via_element_id": eid,
                        "path": path,
                        "path_summary": _path_summary(path),
                    }
                )
            if not hops:
                continue
            af = finding_by_id[anchor_id]
            doc_names = []
            for r in refs:
                if r.element_id == eid and r.document_id in doc_by_id:
                    doc_names.append(doc_by_id[r.document_id].original_name)
            doc_names = sorted(set(doc_names))
            narrative = _narrative(af, hops, el, doc_names)
            chains.append(
                {
                    "anchor_finding_id": anchor_id,
                    "anchor_finding_code": af.code,
                    "anchor_title": af.title,
                    "shared_element": {
                        "id": el.id,
                        "element_type": el.element_type,
                        "type_mark": el.type_mark,
                        "name_label": el.name_label,
                        "match_key": el.match_key,
                        "ifc_global_id": el.ifc_global_id,
                        "drawing_ref": el.drawing_ref,
                    },
                    "documents": doc_names,
                    "related_findings": hops,
                    "hop_count": len(hops),
                    "narrative": narrative,
                }
            )

    # Prefer denser chains; one chain per anchor+element is enough
    chains.sort(key=lambda c: (-c["hop_count"], c["anchor_finding_id"]))
    return chains


async def build_chains_for_analysis(
    db: AsyncSession,
    *,
    project_id: int,
    analysis_id: int,
    documents: list[Document] | None = None,
) -> dict[str, Any]:
    """Link findings into graph then build related_findings_chain payload."""
    link_stats = await link_findings_into_graph(
        db, project_id=project_id, analysis_id=analysis_id, documents=documents
    )
    chains = await build_related_findings_chains(
        db, project_id=project_id, analysis_id=analysis_id
    )
    return {
        "link_stats": link_stats,
        "related_findings_chain": chains,
        "chain_count": len(chains),
    }


# ----- helpers -----


def _resolve_document_ids(
    blob: str,
    docs_by_id: dict[int, Document],
    docs_by_name: dict[str, Document],
) -> set[int]:
    found: set[int] = set()
    lower = blob.lower()
    for name, doc in docs_by_name.items():
        if name and name in lower:
            found.add(doc.id)
    for m in _DOC_NAME_RE.finditer(blob):
        name = (m.group(1) or m.group(2) or m.group(3) or "").strip().lower()
        if name in docs_by_name:
            found.add(docs_by_name[name].id)
    # document_id=123 in cause chain
    for m in re.finditer(r"document(?:_id)?[=:](\d+)", blob, re.I):
        did = int(m.group(1))
        if did in docs_by_id:
            found.add(did)
    return found


def _resolve_element_ids(
    blob: str,
    elements: list[ProjectElement],
    doc_ids: set[int],
    elements_by_doc: dict[int, set[int]],
) -> set[int]:
    found: set[int] = set()
    lower = blob.lower()
    for el in elements:
        marks = [
            (el.type_mark or "").lower(),
            (el.name_label or "").lower(),
            (el.match_key or "").lower(),
            (el.ifc_global_id or "").lower(),
        ]
        for mark in marks:
            if mark and len(mark) >= 3 and mark in lower:
                found.add(el.id)
                break
    for m in _MARK_RE.finditer(blob):
        mark = m.group(1).lower()
        for el in elements:
            if (el.type_mark or "").lower() == mark or (el.name_label or "").lower() == mark:
                found.add(el.id)
    for did in doc_ids:
        found |= elements_by_doc.get(did, set())
    return found


def _shortest_path(
    adj: dict[tuple[str, str], list[tuple[str, str, str, int]]],
    *,
    start: tuple[str, str],
    goal: tuple[str, str],
    max_hops: int,
) -> list[dict[str, Any]]:
    if start == goal:
        return [{"node": f"{start[0]}:{start[1]}", "predicate": None}]
    q: deque[tuple[tuple[str, str], list[dict[str, Any]]]] = deque([(start, [{"node": f"{start[0]}:{start[1]}", "predicate": None}])])
    seen = {start}
    while q:
        node, path = q.popleft()
        if len(path) - 1 >= max_hops:
            continue
        for pred, t_type, t_id, _eid in adj.get(node, []):
            nxt = (t_type, t_id)
            if nxt in seen:
                continue
            seen.add(nxt)
            new_path = path + [{"node": f"{t_type}:{t_id}", "predicate": pred}]
            if nxt == goal:
                return new_path
            q.append((nxt, new_path))
    return []


def _path_summary(path: list[dict[str, Any]]) -> str:
    if not path:
        return ""
    parts = [str(path[0].get("node"))]
    for step in path[1:]:
        pred = step.get("predicate") or "linked_to"
        pred = str(pred).removeprefix("inv:")
        parts.append(f"—{pred}→")
        parts.append(str(step.get("node")))
    return " ".join(parts)


def _narrative(
    anchor: Finding,
    hops: list[dict[str, Any]],
    element: ProjectElement,
    doc_names: list[str],
) -> str:
    mark = element.type_mark or element.name_label or element.match_key or f"element#{element.id}"
    bits = [
        f"This {anchor.code} finding (#{anchor.id}: {anchor.title}) connects to "
    ]
    rels = []
    for h in hops:
        rels.append(f"{h['code']} (#{h['finding_id']}: {h['title']})")
    bits.append("; ".join(rels))
    bits.append(f" via shared Element {mark} (id={element.id}, match_key={element.match_key})")
    if element.ifc_global_id:
        bits.append(f" [IFC {element.ifc_global_id}]")
    if doc_names:
        bits.append(f" across documents: {', '.join(doc_names)}")
    bits.append(".")
    return "".join(bits)
