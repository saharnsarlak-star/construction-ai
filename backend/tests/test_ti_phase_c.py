"""Unit + integration tests for Phase C / TI-1 semantic tender intelligence."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import LanguageCode, RiskSeverity
from app.models import CountryCode
from app.services.analyzer import RiskFinding, analyze_project_documents
from app.services.tender_intelligence import (
    TI_RISK_ID,
    _finding_from_gap,
    _llm_not_configured_finding,
    link_ti_findings_to_graph,
)
from app.standards_engine.compliance.semantic_compliance import (
    SemanticCoverageResult,
    check_requirement_semantic,
    check_requirements_semantic_batch,
)


class MockLLMClient:
    """Deterministic LLM double for TI-1 tests."""

    provider = "mock"

    @property
    def is_configured(self) -> bool:
        return True

    def chat_json(self, *, system: str, user: str, call_key: str | None = None, temperature: float = 0.0):
        payload = json.loads(user)
        status = "silent"
        if "contradict" in str(payload.get("tender_excerpt") or "").lower():
            status = "contradictory"
        elif len(str(payload.get("tender_excerpt") or "")) > 200:
            status = "partial"
        parsed = {
            "coverage_status": status,
            "severity": "high" if status in {"silent", "contradictory"} else "medium",
            "reasoning": f"Mock semantic: {status}",
            "tender_excerpt": (payload.get("tender_excerpt") or "")[:100],
        }
        resp = MagicMock()
        resp.parsed = parsed
        return resp


class FindingBuilderTests(unittest.TestCase):
    def test_finding_uses_valid_rkb_risk_id(self) -> None:
        gap = SemanticCoverageResult(
            requirement_id=42,
            clause_number="2-2-3-1",
            standard_code="CODE55-VOL1-IR",
            requirement_text="Corridor minimum height 2.5m",
            coverage_status="silent",
            severity="high",
            reasoning="No tender coverage",
            source_page=10,
        )
        f = _finding_from_gap(gap, lang=LanguageCode.EN, index=1)
        self.assertEqual(f.source_layer, "llm_based")
        self.assertIn(f"risk_id={TI_RISK_ID}", f.cause_effect_chain)
        self.assertEqual(f.source_page, 10)
        self.assertTrue(f.code.startswith("TI-STD-"))

    def test_contradictory_is_llm_based_not_hybrid(self) -> None:
        gap = SemanticCoverageResult(
            requirement_id=1,
            clause_number="2-2-3-2",
            standard_code="CODE55-VOL1-IR",
            requirement_text="Fire rating REI 90",
            coverage_status="contradictory",
            severity="high",
            reasoning="Conflict detected",
        )
        f = _finding_from_gap(gap, lang=LanguageCode.EN, index=1)
        self.assertEqual(f.source_layer, "llm_based")
        self.assertEqual(f.severity, RiskSeverity.HIGH)

    def test_partial_finding_severity(self) -> None:
        gap = SemanticCoverageResult(
            requirement_id=2,
            clause_number="2-2-3-3",
            standard_code="CODE55-VOL1-IR",
            requirement_text="Minimum corridor width 1.2m",
            coverage_status="partial",
            severity="medium",
            reasoning="Related topic only",
        )
        f = _finding_from_gap(gap, lang=LanguageCode.EN, index=1)
        self.assertEqual(f.severity, RiskSeverity.MEDIUM)

    def test_llm_not_configured_is_limitation(self) -> None:
        f = _llm_not_configured_finding(LanguageCode.EN)
        self.assertEqual(f.finding_category, "limitation")
        self.assertEqual(f.code, "TI-LLM-NOT-CONFIGURED")


class SemanticComplianceTests(unittest.TestCase):
    def test_batch_returns_llm_not_configured_meta(self) -> None:
        mock = MagicMock()
        mock.is_configured = False
        gaps, meta = check_requirements_semantic_batch(
            [{"id": 1, "clause_number": "1", "requirement_text": "test"}],
            "tender text",
            standard_code="TEST",
            llm=mock,
        )
        self.assertEqual(gaps, [])
        self.assertFalse(meta["llm_configured"])

    def test_batch_finds_silent_gap_with_mock_llm(self) -> None:
        reqs = [{"id": 5, "clause_number": "2-2-3-1", "requirement_text": "Min height 2.5m", "source_page": 3}]
        gaps, meta = check_requirements_semantic_batch(
            reqs,
            "short",
            standard_code="CODE55-VOL1-IR",
            llm=MockLLMClient(),
        )
        self.assertTrue(meta["llm_configured"])
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].coverage_status, "silent")

    def test_batch_finds_partial_gap(self) -> None:
        reqs = [{"id": 6, "clause_number": "2-2-3-2", "requirement_text": "Min width 1.2m"}]
        long_tender = "Construction scope with walls and corridors described in detail. " * 20
        gaps, meta = check_requirements_semantic_batch(
            reqs,
            long_tender,
            standard_code="CODE55-VOL1-IR",
            llm=MockLLMClient(),
        )
        self.assertTrue(meta["llm_configured"])
        self.assertEqual(gaps[0].coverage_status, "partial")

    def test_check_requirement_contradictory(self) -> None:
        req = {"id": 1, "clause_number": "2-2-3-1", "requirement_text": "Fire rating REI 90"}
        hit = check_requirement_semantic(
            req,
            "The wall must contradict the fire standard",
            standard_code="CODE55-VOL1-IR",
            clause_number="2-2-3-1",
            llm=MockLLMClient(),
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.coverage_status, "contradictory")


class AnalyzerGatingTests(unittest.TestCase):
    def test_skip_keyword_standards_when_ti_active(self) -> None:
        from unittest.mock import patch

        docs = [
            {
                "category": "tender",
                "original_name": "tender.txt",
                "extracted_text": "General construction scope with enough readable text. " * 15,
            }
        ]
        stds = [{"code": "CODE55-VOL1-IR", "title": "Code 55", "standard_class": "technical", "is_selected": True}]
        with patch("app.services.analyzer._analyze_selected_standards_semantic") as mock_sem:
            mock_sem.return_value = []
            analyze_project_documents(
                country=CountryCode.IR,
                report_language=LanguageCode.EN,
                documents=docs,
                selected_standards=stds,
                skip_keyword_standards=True,
            )
            mock_sem.assert_not_called()
            analyze_project_documents(
                country=CountryCode.IR,
                report_language=LanguageCode.EN,
                documents=docs,
                selected_standards=stds,
                skip_keyword_standards=False,
            )
            mock_sem.assert_called_once()


class TIGraphLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_ti_finding_creates_clause_and_requirement_edges(self) -> None:
        from app.models import Analysis, Finding, Project
        from tests.test_kg_phase_b import _create_subset_tables

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await _create_subset_tables(conn, "projects", "analyses", "findings", "ontology_edges")

        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            project = Project(name="TIGraphTest")
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
                code="TI-STD-TEST-2-2-3-1-1",
                category="compliance",
                severity=RiskSeverity.HIGH,
                title="Silent",
                description="Test",
                recommendation="Fix",
            )
            db.add(finding)
            await db.flush()

            ti_finding = RiskFinding(
                code="TI-STD-TEST-2-2-3-1-1",
                category="compliance",
                severity=RiskSeverity.HIGH,
                title="Silent",
                description="Test",
                recommendation="Fix",
                evidence="test",
                source_layer="llm_based",
                cause_effect_chain=[
                    "requirement_id=99",
                    "coverage_status=silent",
                    "clause_number=2-2-3-1",
                ],
            )

            with patch(
                "app.services.tender_intelligence.link_finding_to_standard_clause",
                new_callable=AsyncMock,
            ) as mock_clause_link:
                with patch(
                    "app.services.tender_intelligence.upsert_ontology_edge",
                    new_callable=AsyncMock,
                ) as mock_req_edge:
                    mock_result = MagicMock()
                    mock_result.first.return_value = (58, 10)
                    with patch.object(db, "execute", new_callable=AsyncMock, return_value=mock_result):
                        linked = await link_ti_findings_to_graph(
                            db,
                            project_id=project.id,
                            finding_rows=[finding],
                            ti_findings=[ti_finding],
                        )
                    mock_clause_link.assert_awaited_once()
                    mock_req_edge.assert_awaited_once()
                    self.assertEqual(linked, 1)
                    req_kwargs = mock_req_edge.await_args.kwargs
                    self.assertEqual(req_kwargs["to_type"], "Requirement")
                    self.assertEqual(req_kwargs["to_id"], 99)
        await engine.dispose()


class AIEngineTISkipTests(unittest.TestCase):
    def test_std_seed_003_skipped_when_kg_enabled(self) -> None:
        from pathlib import Path

        text = Path(__file__).resolve().parents[1].joinpath(
            "app", "services", "rule_engine", "ai_engine.py"
        ).read_text(encoding="utf-8")
        self.assertIn("skipped_ti1_active", text)
        self.assertIn("standard_clause_semantic_compliance", text)


class BridgePredicateTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflicts_with_predicate_allowed(self) -> None:
        from app.services.standards_kg_bridge import link_finding_to_standard_clause

        db = AsyncMock()
        with patch(
            "app.services.standards_kg_bridge.upsert_ontology_edge",
            new_callable=AsyncMock,
        ) as mock_upsert:
            await link_finding_to_standard_clause(
                db,
                project_id=1,
                finding_id=5,
                clause_id=10,
                predicate="conflicts_with",
            )
            self.assertEqual(mock_upsert.await_args.kwargs["predicate"], "conflicts_with")


class ProjectsWiringTests(unittest.TestCase):
    def test_ti_gated_on_knowledge_graph_flag(self) -> None:
        from pathlib import Path

        text = Path(__file__).resolve().parents[1].joinpath("app", "routers", "projects.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("run_semantic_standards_compliance", text)
        self.assertIn("skip_keyword_standards=settings.ti_semantic_active", text)
        self.assertIn("link_ti_findings_to_graph", text)


if __name__ == "__main__":
    unittest.main()
