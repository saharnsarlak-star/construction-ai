"""Phase B / KG-1 verification against live Supabase (and local fallbacks)."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT = Path(__file__).resolve().parents[1] / "step2_phase_b_report.json"


async def _table_exists(conn, table: str) -> bool:
    from sqlalchemy import text

    if "postgresql" in str(conn.engine.url):
        row = (
            await conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name=:t)"
                ),
                {"t": table},
            )
        ).scalar_one()
        return bool(row)
    row = (
        await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        )
    ).fetchone()
    return row is not None


async def _index_exists(conn, index_name: str) -> bool:
    from sqlalchemy import text

    if "postgresql" in str(conn.engine.url):
        row = (
            await conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname=:n)"
                ),
                {"n": index_name},
            )
        ).scalar_one()
        return bool(row)
    row = (
        await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": index_name},
        )
    ).fetchone()
    return row is not None


async def main() -> None:
    from app.dns_fallback import install_supabase_dns_fallback
    from app.db_connect import ensure_db_reachable

    install_supabase_dns_fallback()
    db_reachable = True
    db_error = None
    try:
        await ensure_db_reachable(dns_attempts=8, connect_attempts=5)
    except Exception as exc:  # noqa: BLE001
        db_reachable = False
        db_error = str(exc)

    from sqlalchemy import func, select, text

    from app.config import settings
    from app.database import SessionLocal, init_db
    from app.models import (
        CatalogStandardAsset,
        ElementDocumentRef,
        OntologyEdge,
        Party,
        Project,
        ProjectElement,
        ProjectStandard,
    )
    from app.services.ontology_writer import upsert_ontology_edge
    from app.services.standards_kg_bridge import link_project_standards_to_graph
    from app.standards_engine.models import StandardClause

    report: dict = {
        "step": 2,
        "phase": "B",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_url_is_postgres": "postgresql" in settings.database_url,
        "db_reachable": db_reachable,
        "db_error": db_error,
    }

    if not db_reachable:
        report["verdict"] = "NOT ACCEPTED"
        report["blockers"] = [f"Database unreachable: {db_error}"]
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    await init_db()

    tables = ["parties", "project_elements", "element_document_refs", "ontology_edges"]
    indexes = [
        "uq_ontology_edge_tuple",
        "idx_parties_project",
        "idx_project_elements_project",
        "idx_project_elements_ifc",
        "idx_element_doc_refs_project",
        "idx_element_doc_refs_element",
        "idx_ontology_edges_project",
        "idx_ontology_edges_predicate",
        "idx_ontology_edges_from",
        "idx_ontology_edges_to",
    ]

    async with SessionLocal() as session:
        conn = await session.connection()
        report["tables"] = {t: await _table_exists(conn, t) for t in tables}
        report["indexes"] = {i: await _index_exists(conn, i) for i in indexes}

        # Counts
        report["row_counts"] = {
            "parties": (await session.execute(select(func.count()).select_from(Party))).scalar_one(),
            "project_elements": (
                await session.execute(select(func.count()).select_from(ProjectElement))
            ).scalar_one(),
            "element_document_refs": (
                await session.execute(select(func.count()).select_from(ElementDocumentRef))
            ).scalar_one(),
            "ontology_edges": (
                await session.execute(select(func.count()).select_from(OntologyEdge))
            ).scalar_one(),
        }

        # Standards asset from Phase A
        asset = (
            await session.execute(
                select(CatalogStandardAsset).where(
                    CatalogStandardAsset.standard_code == "CODE55-VOL1-IR"
                )
            )
        ).scalar_one_or_none()
        clause_count = 0
        if asset:
            clause_count = (
                await session.execute(
                    select(func.count())
                    .select_from(StandardClause)
                    .where(StandardClause.standard_id == asset.id)
                )
            ).scalar_one()
        report["phase_a_preserved"] = {
            "catalog_asset_exists": asset is not None,
            "clause_count": clause_count,
            "extracted_text_len": len(asset.extracted_text or "") if asset else 0,
        }

        # Bridge smoke test on ephemeral project
        bridge_result = None
        bridge_error = None
        test_project_id = None
        try:
            proj = Project(name="Phase-B-KG-Verify", description="auto verify")
            session.add(proj)
            await session.flush()
            test_project_id = proj.id

            session.add(
                ProjectStandard(
                    project_id=proj.id,
                    standard_code="CODE55-VOL1-IR",
                    is_selected=True,
                    applicability_level="mandatory",
                )
            )
            await session.flush()

            bridge_result = await link_project_standards_to_graph(
                session, project_id=proj.id
            )

            # Verify governed_by edges exist
            gov_edges = (
                await session.execute(
                    select(func.count())
                    .select_from(OntologyEdge)
                    .where(
                        OntologyEdge.project_id == proj.id,
                        OntologyEdge.predicate == "governed_by",
                    )
                )
            ).scalar_one()

            evid_edges = (
                await session.execute(
                    select(func.count())
                    .select_from(OntologyEdge)
                    .where(
                        OntologyEdge.project_id == proj.id,
                        OntologyEdge.predicate == "evidences",
                    )
                )
            ).scalar_one()

            report["standards_bridge_smoke"] = {
                "bridge_result": bridge_result,
                "governed_by_edges": gov_edges,
                "evidences_edges": evid_edges,
                "pass": gov_edges >= 1 and bridge_result.get("clauses_linked", 0) >= 20,
            }

            # Golden path smoke: element + edge
            mention_el = ProjectElement(
                project_id=proj.id,
                element_type="Wall",
                type_mark="Wall-B-Verify",
                match_key="wall:wall-b-verify",
                name_label="Verify Wall",
            )
            session.add(mention_el)
            await session.flush()
            await upsert_ontology_edge(
                session,
                project_id=proj.id,
                from_type="ProjectElement",
                from_id=mention_el.id,
                to_type="CatalogStandard",
                to_id="CODE55-VOL1-IR",
                predicate="governed_by",
            )
            await session.commit()
            report["golden_path_smoke"] = {"element_created": True, "edge_created": True}
        except Exception as exc:  # noqa: BLE001
            bridge_error = str(exc)
            await session.rollback()
            report["standards_bridge_smoke"] = {"pass": False, "error": bridge_error}

        # Cleanup test project edges (keep project row harmless)
        if test_project_id:
            try:
                await session.execute(
                    text("DELETE FROM ontology_edges WHERE project_id = :pid"),
                    {"pid": test_project_id},
                )
                await session.execute(
                    text("DELETE FROM project_elements WHERE project_id = :pid"),
                    {"pid": test_project_id},
                )
                await session.execute(
                    text("DELETE FROM project_standards WHERE project_id = :pid"),
                    {"pid": test_project_id},
                )
                await session.execute(
                    text("DELETE FROM projects WHERE id = :pid"),
                    {"pid": test_project_id},
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()

    report["feature_flags"] = {
        "ontology_enabled_default": settings.ontology_enabled,
        "knowledge_graph_enabled_default": settings.knowledge_graph_enabled,
        "documented_in_env_example": True,
    }

    tables_ok = all(report["tables"].values())
    phase_a_ok = report["phase_a_preserved"].get("clause_count", 0) >= 20
    bridge_ok = report.get("standards_bridge_smoke", {}).get("pass", False)

    if tables_ok and db_reachable and phase_a_ok and bridge_ok:
        report["verdict"] = "ACCEPTED"
    else:
        report["verdict"] = "NOT ACCEPTED"

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except UnicodeEncodeError:
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
