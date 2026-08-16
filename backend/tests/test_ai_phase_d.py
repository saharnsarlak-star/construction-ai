"""Unit + integration tests for Phase D / AI-HYBRID seed rule engine."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType, RiskSeverity
from app.services.analyzer import RiskFinding
from app.services.finding_guardrail import apply_finding_guardrail, apply_guardrails_to_findings
from app.services.rule_engine.ai_engine import (
    _llm_not_configured_finding,
    list_ai_hybrid_seed_rules,
    run_ai_hybrid_seed_rules,
)
from app.services.rule_engine.context import RuleContext, build_doc_view
from app.services.rule_engine.hybrid_detectors import _DETECTORS, detect_hybrid_discrepancy


CONTRACT_DRAINAGE = """CONSTRUCTION CONTRACT AGREEMENT
Clause 8.4 — Site Drainage
The Contractor shall provide temporary site drainage if necessary to keep the works dry.
Clause 12.1 — Performance Bond
The Contractor shall provide a performance bond of 10% of the Contract Price.
Elsewhere: performance guarantee may be 5% or equivalent security may be waived by Employer.
Completion date: 2026-12-15
Commencement date: 2026-02-01
"""

ITT_DOC = """INSTRUCTIONS TO TENDERERS
Bid deadline: 2025-11-30
Completion date: 2026-10-01
Start date: 2026-03-01
"""

ER_FIRE = """Employer Requirements
Fire protection may be omitted in non-critical areas.
"""


class PhaseDMockLLM:
    provider = "mock_phase_d"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def model(self) -> str:
        return "mock_phase_d"

    def chat_json(self, *, system: str, user: str, call_key: str | None = None, temperature: float = 0.0):
        payload = json.loads(user)
        mode = str(payload.get("mode") or "")
        rule = payload.get("rule") or {}
        code = str(rule.get("code") or call_key or "UNKNOWN")
        excerpts = payload.get("excerpts") or []
        quote = str(excerpts[0].get("text") or "")[:200] if excerpts else "sample excerpt"
        if mode == "hybrid_explain":
            parsed = {
                "triggered": True,
                "confidence_score": 85,
                "title": str(rule.get("title") or code),
                "description": "Hybrid explain from mock.",
                "recommendation": "Reconcile documents.",
                "source_excerpt": quote,
                "document_name": "contract",
                "location": "Clause 8.4",
                "reasoning": "Python discrepancy explained by mock LLM.",
            }
        else:
            parsed = {
                "triggered": True,
                "confidence_score": 88,
                "title": str(rule.get("title") or code),
                "description": "AI ambiguity detected by mock.",
                "recommendation": "Clarify wording.",
                "source_excerpt": quote,
                "document_name": "contract",
                "location": "Clause 8.4",
                "reasoning": "Mock AI detect.",
            }
        resp = MagicMock()
        resp.parsed = parsed
        resp.usage = MagicMock(latency_ms=10.0, prompt_tokens=50, completion_tokens=30, model="mock")
        return resp


class UnconfiguredLLM:
    provider = "none"

    @property
    def is_configured(self) -> bool:
        return False

    @property
    def model(self) -> str:
        return "none"


def _sample_docs() -> list[dict]:
    return [
        {
            "id": 1,
            "category": DocumentCategory.TENDER.value,
            "original_name": "contract.txt",
            "extracted_text": CONTRACT_DRAINAGE,
        },
        {
            "id": 2,
            "category": DocumentCategory.TENDER.value,
            "original_name": "itt.txt",
            "extracted_text": ITT_DOC,
        },
    ]


class RuleInventoryTests(unittest.TestCase):
    def test_list_ai_hybrid_seed_rules_count(self) -> None:
        rules = list_ai_hybrid_seed_rules()
        self.assertEqual(len(rules), 24)
        tags = {(r.logic_config or {}).get("ownership_tag") for r in rules}
        self.assertEqual(tags, {"AI", "HYBRID"})
        ai_count = sum(1 for r in rules if (r.logic_config or {}).get("ownership_tag") == "AI")
        hybrid_count = sum(1 for r in rules if (r.logic_config or {}).get("ownership_tag") == "HYBRID")
        self.assertEqual(ai_count, 9)
        self.assertEqual(hybrid_count, 15)

    def test_con_seed_001_present(self) -> None:
        codes = {r.code for r in list_ai_hybrid_seed_rules()}
        self.assertIn("CON-SEED-001", codes)


class HybridDetectorTests(unittest.TestCase):
    def test_all_hybrid_detectors_registered(self) -> None:
        checks = {
            str((r.logic_config or {}).get("check") or "")
            for r in list_ai_hybrid_seed_rules()
            if (r.logic_config or {}).get("ownership_tag") == "HYBRID"
        }
        self.assertEqual(len(_DETECTORS), 15)
        self.assertTrue(checks <= set(_DETECTORS.keys()))

    def test_contract_vs_itt_deadlines_python_first(self) -> None:
        ctx = RuleContext(
            project_id=1,
            country=CountryCode.DE.value,
            project_type=ProjectType.INFRASTRUCTURE,
            documents=[build_doc_view(d) for d in _sample_docs()],
            selected_standards=[],
            elements=[],
        )
        disc = detect_hybrid_discrepancy("contract_vs_itt_deadlines", ctx)
        self.assertIsNotNone(disc)
        self.assertIn("completion", (disc.summary or "").lower())

    def test_er_vs_standard_clause_requires_fire_standard(self) -> None:
        ctx_no_std = RuleContext(
            project_id=1,
            country=CountryCode.DE.value,
            project_type=ProjectType.INFRASTRUCTURE,
            documents=[build_doc_view({
                "id": 1,
                "category": DocumentCategory.TENDER.value,
                "original_name": "employer_requirements.txt",
                "extracted_text": ER_FIRE,
            })],
            selected_standards=[{"code": "CODE55-VOL1-IR"}],
            elements=[],
        )
        self.assertIsNotNone(detect_hybrid_discrepancy("er_vs_standard_clause", ctx_no_std))

        ctx_unrelated = RuleContext(
            project_id=1,
            country=CountryCode.DE.value,
            project_type=ProjectType.INFRASTRUCTURE,
            documents=[build_doc_view({
                "id": 1,
                "category": DocumentCategory.TENDER.value,
                "original_name": "employer_requirements.txt",
                "extracted_text": ER_FIRE,
            })],
            selected_standards=[{"code": "GENERIC-CIVIL-001"}],
            elements=[],
        )
        self.assertIsNone(detect_hybrid_discrepancy("er_vs_standard_clause", ctx_unrelated))

    def test_std_seed_003_uses_db_requirements_overlap(self) -> None:
        ctx = RuleContext(
            project_id=1,
            country=CountryCode.DE.value,
            project_type=ProjectType.INFRASTRUCTURE,
            documents=[build_doc_view({
                "id": 1,
                "category": DocumentCategory.TENDER.value,
                "original_name": "tender.txt",
                "extracted_text": "General construction scope only.",
            })],
            selected_standards=[{"code": "CODE55-VOL1-IR", "is_selected": True}],
            standard_requirements=[
                {
                    "standard_code": "CODE55-VOL1-IR",
                    "requirement_text": "Corridor minimum height 2.5 meters fire rating REI 90",
                    "text": "Corridor minimum height 2.5 meters fire rating REI 90",
                }
            ],
            elements=[],
        )
        disc = detect_hybrid_discrepancy("standard_clause_semantic_compliance", ctx)
        self.assertIsNotNone(disc)
        self.assertIn("silent", (disc.summary or "").lower())


class AIEngineTests(unittest.TestCase):
    def test_llm_not_configured_diagnostic(self) -> None:
        f = _llm_not_configured_finding(LanguageCode.EN)
        self.assertEqual(f.code, "AI-LLM-NOT-CONFIGURED")
        self.assertEqual(f.finding_category, "limitation")
        self.assertEqual(f.source_layer, "python")

    def test_unconfigured_llm_returns_diagnostic(self) -> None:
        findings, metrics = run_ai_hybrid_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=_sample_docs(),
            llm=UnconfiguredLLM(),
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, "AI-LLM-NOT-CONFIGURED")
        self.assertFalse(metrics.get("llm_configured"))

    def test_mock_llm_produces_hybrid_and_ai_layers(self) -> None:
        findings, metrics = run_ai_hybrid_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=_sample_docs(),
            llm=PhaseDMockLLM(),
        )
        layers = {f.source_layer for f in findings}
        self.assertTrue(layers & {"hybrid", "llm_based"})
        self.assertGreater(metrics.get("calls", 0), 0)

    def test_con_seed_001_fires_with_excerpt(self) -> None:
        findings, _ = run_ai_hybrid_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=_sample_docs(),
            llm=PhaseDMockLLM(),
        )
        con = next((f for f in findings if f.code == "CON-SEED-001"), None)
        self.assertIsNotNone(con, "CON-SEED-001 should fire on drainage ambiguity corpus")
        self.assertTrue((con.source_excerpt or con.evidence or "").strip())

    @patch("app.services.rule_engine.ai_engine.settings")
    def test_std_seed_003_skipped_when_ti_active(self, mock_settings) -> None:
        mock_settings.ti_semantic_active = True
        mock_settings.ai_max_calls_per_analysis = 24
        findings, metrics = run_ai_hybrid_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=_sample_docs(),
            selected_standards=[{"code": "CODE55-VOL1-IR", "title": "Code 55"}],
            llm=PhaseDMockLLM(),
        )
        self.assertGreaterEqual(int(metrics.get("skipped_ti1_active") or 0), 1)
        std_codes = {f.code for f in findings}
        self.assertNotIn("STD-SEED-003", std_codes)

    @patch("app.services.rule_engine.ai_engine.settings")
    def test_no_truncation_with_default_cap(self, mock_settings) -> None:
        mock_settings.knowledge_graph_enabled = False
        mock_settings.ai_max_calls_per_analysis = 24
        _, metrics = run_ai_hybrid_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=_sample_docs(),
            llm=PhaseDMockLLM(),
        )
        self.assertFalse(metrics.get("truncated"))


class GuardrailTests(unittest.TestCase):
    def test_ai_finding_without_evidence_downgraded(self) -> None:
        finding = RiskFinding(
            code="AI-PROBE",
            category="contract",
            severity=RiskSeverity.HIGH,
            title="No evidence",
            description="Missing excerpt.",
            recommendation="",
            evidence="",
            source_excerpt="",
            finding_category="risk",
            source_layer="llm_based",
            cause_effect_chain=["source_layer=llm_based"],
        )
        guarded, event = apply_finding_guardrail(finding)
        self.assertEqual(guarded.finding_category, "limitation")
        self.assertIsNotNone(event)

    def test_ai_finding_with_evidence_passes_guardrail(self) -> None:
        finding = RiskFinding(
            code="CON-SEED-001",
            category="contract",
            severity=RiskSeverity.HIGH,
            title="Ambiguous drainage",
            description="Non-measurable obligation language.",
            recommendation="Define measurable criteria.",
            evidence="Clause 8.4: if necessary",
            source_excerpt="if necessary",
            source_document_name="contract.txt",
            finding_category="risk",
            source_layer="llm_based",
            cause_effect_chain=["risk_id=RISK-CON-001", "source_layer=llm_based"],
        )
        guarded, events = apply_guardrails_to_findings([finding])
        self.assertEqual(len(guarded), 1)
        self.assertEqual(guarded[0].finding_category, "risk")
        self.assertEqual(events, [])


class WiringTests(unittest.TestCase):
    def test_projects_wires_ai_engine(self) -> None:
        src = (os.path.join(os.path.dirname(__file__), "..", "app", "routers", "projects.py"))
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("settings.ai_rule_engine_enabled", text)
        self.assertIn("run_ai_hybrid_seed_rules", text)
        self.assertIn('f.code != "AI-LLM-NOT-CONFIGURED"', text)

    def test_ai_engine_default_flag_off(self) -> None:
        from app.config import Settings

        self.assertFalse(Settings.model_fields["ai_rule_engine_enabled"].default)

    def test_ai_max_calls_default_covers_all_rules(self) -> None:
        from app.config import Settings

        self.assertEqual(Settings.model_fields["ai_max_calls_per_analysis"].default, 24)


if __name__ == "__main__":
    unittest.main()
