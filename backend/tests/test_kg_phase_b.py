"""Unit + integration tests for Phase B / KG-1 infrastructure."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import RiskSeverity
from app.services.analyzer import RiskFinding
from app.services.finding_guardrail import apply_finding_guardrail, apply_guardrails_to_findings
from app.services.ontology_writer import (
    ElementMention,
    attach_document_ref,
    build_match_key,
    resolve_or_create_element,
)
from app.services.standards_kg_bridge import link_finding_to_standard_clause


def _ontology_subset_tables():
    from app.database import Base
    from app.models import (
        Analysis,
        Document,
        ElementDocumentRef,
        Finding,
        OntologyEdge,
        Party,
        Project,
        ProjectElement,
    )

    return Base, (
        Project.__table__,
        Document.__table__,
        ProjectElement.__table__,
        ElementDocumentRef.__table__,
        OntologyEdge.__table__,
        Party.__table__,
        Analysis.__table__,
        Finding.__table__,
    )


async def _create_subset_tables(conn, *table_names: str) -> None:
    base, all_tables = _ontology_subset_tables()
    if table_names:
        wanted = set(table_names)
        tables = [t for t in all_tables if t.name in wanted]
    else:
        tables = [
            t
            for t in all_tables
            if t.name
            in {
                "projects",
                "documents",
                "project_elements",
                "element_document_refs",
                "ontology_edges",
                "parties",
            }
        ]
    await conn.run_sync(lambda sync_conn: base.metadata.create_all(sync_conn, tables=tables))


class FindingGuardrailTests(unittest.TestCase):
    def _high_finding(self, **kwargs) -> RiskFinding:
        base = dict(
            code="TEST-001",
            category="scope",
            severity=RiskSeverity.HIGH,
            title="Test",
            description="Test description",
            recommendation="Review this",
            evidence="Document excerpt here",
            source_layer="rule_based",
            cause_effect_chain=["risk_id=CLAIM-001", "source_layer=rule_based"],
        )
        base.update(kwargs)
        return RiskFinding(**base)

    def test_passes_with_full_evidence(self) -> None:
        f = self._high_finding()
        updated, event = apply_finding_guardrail(f)
        self.assertIsNone(event)
        self.assertEqual(updated.severity, RiskSeverity.HIGH)

    def test_downgrades_without_evidence(self) -> None:
        f = self._high_finding(
            evidence=None,
            source_excerpt=None,
            source_document_name=None,
            recommendation=None,
        )
        updated, event = apply_finding_guardrail(f)
        self.assertIsNotNone(event)
        self.assertEqual(updated.finding_category, "limitation")
        self.assertEqual(updated.severity, RiskSeverity.LOW)
        self.assertIn("evidence", event["missing"])

    def test_batch_guardrails(self) -> None:
        findings = [
            self._high_finding(),
            self._high_finding(code="TEST-002", evidence=None, source_excerpt=None, recommendation=None),
        ]
        out, events = apply_guardrails_to_findings(findings)
        self.assertEqual(len(out), 2)
        self.assertEqual(len(events), 1)

    def test_low_severity_untouched(self) -> None:
        f = self._high_finding(severity=RiskSeverity.LOW, evidence=None)
        updated, event = apply_finding_guardrail(f)
        self.assertIsNone(event)
        self.assertEqual(updated.severity, RiskSeverity.LOW)


class OntologyWriterUnitTests(unittest.TestCase):
    def test_build_match_key_type_mark(self) -> None:
        key = build_match_key(element_type="Wall", type_mark="Wall-A")
        self.assertEqual(key, "wall:wall-a")

    def test_build_match_key_with_drawing(self) -> None:
        key = build_match_key(
            element_type="Wall",
            type_mark="W-01",
            drawing_ref="A-101",
            prefer_drawing=True,
        )
        self.assertIn("a-101", key)
        self.assertIn("wall", key)


class FeatureFlagInteractionTests(unittest.TestCase):
    def test_defaults_off(self) -> None:
        from app.config import Settings

        s = Settings(_env_file=None)
        self.assertFalse(s.ontology_enabled)
        self.assertFalse(s.knowledge_graph_enabled)

    def test_env_flag_matrix(self) -> None:
        from app.config import Settings

        saved = {
            k: os.environ.pop(k, None)
            for k in ("ONTOLOGY_ENABLED", "KNOWLEDGE_GRAPH_ENABLED")
        }
        try:
            os.environ["ONTOLOGY_ENABLED"] = "true"
            os.environ["KNOWLEDGE_GRAPH_ENABLED"] = "false"
            s = Settings(_env_file=None)
            self.assertTrue(s.ontology_enabled)
            self.assertFalse(s.knowledge_graph_enabled)

            os.environ["ONTOLOGY_ENABLED"] = "false"
            os.environ["KNOWLEDGE_GRAPH_ENABLED"] = "on"
            s2 = Settings(_env_file=None)
            self.assertFalse(s2.ontology_enabled)
            self.assertTrue(s2.knowledge_graph_enabled)

            os.environ["ONTOLOGY_ENABLED"] = "1"
            os.environ["KNOWLEDGE_GRAPH_ENABLED"] = "yes"
            s3 = Settings(_env_file=None)
            self.assertTrue(s3.ontology_enabled)
            self.assertTrue(s3.knowledge_graph_enabled)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
                elif k in os.environ:
                    del os.environ[k]

    def test_standards_bridge_requires_both_flags(self) -> None:
        """Documented contract: link_project_standards_to_graph only when both flags true."""
        source = Path(__file__).resolve().parents[1] / "app" / "routers" / "projects.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("if settings.knowledge_graph_enabled:", text)
        self.assertIn("if settings.ontology_enabled:", text)
        self.assertIn("link_project_standards_to_graph", text)


class GoldenPathIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_or_create_merges_by_match_key(self) -> None:
        from app.models import Project, ProjectElement

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await _create_subset_tables(conn)

        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            project = Project(name="GoldenPathTest")
            db.add(project)
            await db.flush()

            m1 = ElementMention(
                element_type="Wall",
                type_mark="Wall-A",
                name_label="Wall-A",
                ifc_global_id="GUID-001",
                confidence=90,
            )
            el1 = await resolve_or_create_element(db, project_id=project.id, mention=m1)

            m2 = ElementMention(
                element_type="Wall",
                type_mark="Wall-A",
                name_label="Wall-A",
                drawing_ref="A-101",
                fire_rating="REI 90",
                confidence=85,
            )
            el2 = await resolve_or_create_element(db, project_id=project.id, mention=m2)

            self.assertEqual(el1.id, el2.id)
            merged = await db.get(ProjectElement, el1.id)
            assert merged is not None
            self.assertEqual(merged.ifc_global_id, "GUID-001")
            self.assertEqual(merged.fire_rating, "REI 90")
            self.assertEqual(merged.drawing_ref, "A-101")

            rows = (await db.execute(select(ProjectElement))).scalars().all()
            self.assertEqual(len(rows), 1)
        await engine.dispose()

    async def test_attach_document_ref_idempotent(self) -> None:
        from app.models import Document, DocumentCategory, ElementDocumentRef, Project, ProjectElement

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await _create_subset_tables(conn)

        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            project = Project(name="RefTest")
            db.add(project)
            await db.flush()
            doc = Document(
                project_id=project.id,
                category=DocumentCategory.TENDER,
                original_name="t.txt",
                stored_path="t.txt",
                content_type="text/plain",
                size_bytes=10,
                extracted_text="Wall-A text",
            )
            db.add(doc)
            await db.flush()

            element = ProjectElement(
                project_id=project.id,
                element_type="Wall",
                type_mark="Wall-A",
                match_key="wall:wall-a",
            )
            db.add(element)
            await db.flush()

            mention = ElementMention(
                element_type="Wall",
                type_mark="Wall-A",
                source_kind="boq_item",
                source_local_id="0100",
                excerpt="Wall-A item",
            )
            ref1 = await attach_document_ref(
                db,
                project_id=project.id,
                element=element,
                document_id=doc.id,
                mention=mention,
            )
            ref2 = await attach_document_ref(
                db,
                project_id=project.id,
                element=element,
                document_id=doc.id,
                mention=mention,
            )
            self.assertEqual(ref1.id, ref2.id)
            refs = (await db.execute(select(ElementDocumentRef))).scalars().all()
            self.assertEqual(len(refs), 1)
        await engine.dispose()


class StandardsBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_finding_to_clause_calls_upsert(self) -> None:
        db = AsyncMock()
        with patch(
            "app.services.standards_kg_bridge.upsert_ontology_edge",
            new_callable=AsyncMock,
        ) as mock_upsert:
            await link_finding_to_standard_clause(
                db,
                project_id=1,
                finding_id=10,
                clause_id=58,
                predicate="gaps",
                evidence={"clause_number": "2-2-7-1"},
            )
            mock_upsert.assert_awaited_once()
            kwargs = mock_upsert.await_args.kwargs
            self.assertEqual(kwargs["from_type"], "Finding")
            self.assertEqual(kwargs["to_type"], "StandardClause")
            self.assertEqual(kwargs["predicate"], "gaps")

    async def test_link_finding_to_clause_persists_edge(self) -> None:
        from app.models import Analysis, Finding, OntologyEdge, Project

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await _create_subset_tables(
                conn, "projects", "analyses", "findings", "ontology_edges"
            )

        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            project = Project(name="FindingLinkTest")
            db.add(project)
            await db.flush()
            analysis = Analysis(
                project_id=project.id,
                status="completed",
                summary="test",
                report_language="en",
            )
            db.add(analysis)
            await db.flush()
            finding = Finding(
                analysis_id=analysis.id,
                code="FL-001",
                category="scope",
                severity=RiskSeverity.LOW,
                title="Test",
                description="Test",
                recommendation="Review",
            )
            db.add(finding)
            await db.flush()

            await link_finding_to_standard_clause(
                db,
                project_id=project.id,
                finding_id=finding.id,
                clause_id=42,
                predicate="gaps",
                evidence={"clause_number": "2-2-3-1"},
            )
            await db.commit()

            edge = (
                await db.execute(
                    select(OntologyEdge).where(
                        OntologyEdge.project_id == project.id,
                        OntologyEdge.from_type == "Finding",
                        OntologyEdge.from_id == str(finding.id),
                        OntologyEdge.predicate == "gaps",
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(edge)
            self.assertEqual(edge.to_type, "StandardClause")
            self.assertEqual(edge.to_id, "42")
        await engine.dispose()


class OntologyTableNamesTests(unittest.TestCase):
    def test_models_registered(self) -> None:
        from app.models import ElementDocumentRef, OntologyEdge, Party, ProjectElement

        self.assertEqual(Party.__tablename__, "parties")
        self.assertEqual(ProjectElement.__tablename__, "project_elements")
        self.assertEqual(ElementDocumentRef.__tablename__, "element_document_refs")
        self.assertEqual(OntologyEdge.__tablename__, "ontology_edges")


if __name__ == "__main__":
    unittest.main()
