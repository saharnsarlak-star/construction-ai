"""Standards Engine ↔ Knowledge Graph bridge (KG-1).

Links project-selected standards and ingested StandardClause rows into the
relational OntologyEdge graph. Platform-level clauses are referenced per-project
via ``governed_by`` and ``evidences`` predicates (Part 5 / Part 6).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogStandardAsset, ProjectStandard
from app.services.ontology_writer import upsert_ontology_edge
from app.standards_engine.models import StandardClause

logger = logging.getLogger(__name__)


async def link_project_standards_to_graph(
    db: AsyncSession,
    *,
    project_id: int,
) -> dict[str, Any]:
    """
    Create OntologyEdge rows from Project → CatalogStandard and Project → StandardClause.

    Does not duplicate edges; safe to call after each analysis.
    """
    selected = (
        await db.execute(
            select(ProjectStandard).where(
                ProjectStandard.project_id == project_id,
                ProjectStandard.is_selected.is_(True),
            )
        )
    ).scalars().all()

    if not selected:
        return {"standards_linked": 0, "clauses_linked": 0, "standard_codes": []}

    edges_before = await _count_project_edges(db, project_id)
    codes = [s.standard_code for s in selected if s.standard_code]
    clauses_linked = 0

    for ps in selected:
        code = (ps.standard_code or "").strip()
        if not code:
            continue

        asset = (
            await db.execute(
                select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == code)
            )
        ).scalar_one_or_none()

        await upsert_ontology_edge(
            db,
            project_id=project_id,
            from_type="Project",
            from_id=project_id,
            to_type="CatalogStandard",
            to_id=code,
            predicate="governed_by",
            confidence=90,
            origin_kind="python",
            evidence={
                "standard_code": code,
                "project_standard_id": ps.id,
                "applicability_level": ps.applicability_level,
            },
        )

        if asset is None:
            continue

        clauses = (
            await db.execute(
                select(StandardClause).where(StandardClause.standard_id == asset.id)
            )
        ).scalars().all()

        for clause in clauses:
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="Project",
                from_id=project_id,
                to_type="StandardClause",
                to_id=clause.id,
                predicate="governed_by",
                confidence=85,
                origin_kind="python",
                evidence={
                    "standard_code": code,
                    "clause_number": clause.clause_number,
                    "source_page": clause.source_page,
                },
            )
            # Reverse navigability for graph traversal
            await upsert_ontology_edge(
                db,
                project_id=project_id,
                from_type="StandardClause",
                from_id=clause.id,
                to_type="Project",
                to_id=project_id,
                predicate="evidences",
                confidence=85,
                origin_kind="python",
                evidence={
                    "standard_code": code,
                    "clause_number": clause.clause_number,
                },
            )
            clauses_linked += 1

    await db.flush()
    edges_after = await _count_project_edges(db, project_id)
    return {
        "standards_linked": len(codes),
        "clauses_linked": clauses_linked,
        "standard_codes": codes,
        "edges_added": max(0, edges_after - edges_before),
    }


async def link_finding_to_standard_clause(
    db: AsyncSession,
    *,
    project_id: int,
    finding_id: int,
    clause_id: int,
    predicate: str = "gaps",
    document_id: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> None:
    """Link a Finding to a StandardClause (compliance gap or evidence)."""
    pred = predicate.strip().lower()
    if pred not in {"gaps", "evidences", "violates", "governed_by", "conflicts_with"}:
        pred = "gaps"
    await upsert_ontology_edge(
        db,
        project_id=project_id,
        from_type="Finding",
        from_id=finding_id,
        to_type="StandardClause",
        to_id=clause_id,
        predicate=pred,
        confidence=80,
        origin_kind="hybrid",
        document_id=document_id,
        evidence=evidence or {"finding_id": finding_id, "clause_id": clause_id},
    )


async def _count_project_edges(db: AsyncSession, project_id: int) -> int:
    from app.models import OntologyEdge

    rows = (
        await db.execute(
            select(OntologyEdge.id).where(OntologyEdge.project_id == project_id)
        )
    ).all()
    return len(rows)
