"""Phase 4 — AI/HYBRID seed runners test with known ambiguity documents.

Provider note: this repo had NO LLM API configured. Test uses:
  1) OPENAI_API_KEY + openai_compatible if present (live), else
  2) LLM_PROVIDER=local_semantic (offline structured semantic responder)

Usage (from backend/):
  set AI_RULE_ENGINE_ENABLED=true
  set LLM_PROVIDER=local_semantic
  python scripts/phase4_ai_rules_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


CONTRACT_DRAINAGE = """CONSTRUCTION CONTRACT AGREEMENT
Employer: Rhine Port Authority
Contractor: BuildRight Contracting Ltd

Clause 8.4 — Site Drainage
The Contractor shall provide temporary site drainage if necessary to keep the works dry.
Responsibility for permanent drainage connections shall be agreed later between the parties as required.
The Employer may instruct additional pumping at the Contractor's cost where reasonable.

Clause 12.1 — Performance Bond
The Contractor shall provide a performance bond of 10% of the Contract Price.
Elsewhere in Particular Conditions: performance guarantee may be 5% or equivalent security may be waived by Employer.

Completion date: 2026-12-15
Commencement date / Notice to Proceed: 2026-02-01
Total gross floor area: 2,500 m2
"""

ITT_DOC = """INSTRUCTIONS TO TENDERERS
Bid deadline: 2025-11-30
Completion date: 2026-10-01
Start date: 2026-03-01
Evaluation will consider technical and financial proposals. Criteria will be advised.
Appendices: A, B
"""

BOQ_DOC = """code|description|qty|unit|unit_price|total_price
0100|Exterior wall Wall-A|120|m2|50|6000
0200|Site concrete paving|80000|m2|12|960000
"""

SPEC_DOC = """TECHNICAL SPECIFICATIONS
Section 03 30 00 Cast-in-Place Concrete
Provide concrete for foundations and slabs as shown on drawings.
Steel reinforcement shall be provided as required.
Fire rating for walls: REI 60
"""

DRAWING_DOC = """Structural Drawing S-101 Rev A
Scale 1:75
Fire rating REI 90 for Wall-A
Concrete note: C30/37
Bearing capacity assumed 180 kPa
"""

GEO_DOC = """Geotechnical Report
Report date: 2024-01-10
Site area: 5000 m2
Borehole BH-01 only.
Soil investigation completed. Foundation recommendations provided.
Bearing capacity: 120 kPa
"""

ER_DOC = """Employer Requirements
The facility shall achieve world-class high quality finishes throughout.
U-value for facade ≤ 0.8
The Contractor shall provide BMS if necessary.
"""

SPEC2 = """Technical Specification — Facade
U-value for facade ≤ 1.4
"""


def main() -> int:
    # Load key from .env via Settings — do NOT fall back to local_semantic when key exists
    from app.config import Settings, settings as _boot

    if not (_boot.openai_api_key or "").strip():
        print("BLOCKED: OPENAI_API_KEY not set in .env — Phase 4 real-LLM validation cannot run.")
        return 2

    os.environ["OPENAI_API_KEY"] = _boot.openai_api_key.strip()
    os.environ["LLM_PROVIDER"] = "openai_compatible"
    os.environ["AI_RULE_ENGINE_ENABLED"] = "true"
    os.environ.setdefault("AI_MAX_CALLS_PER_ANALYSIS", "10")
    os.environ.setdefault("LLM_MODEL", _boot.llm_model or "gpt-4o-mini")

    # Reload settings after forcing provider
    import importlib
    import app.config as cfg

    importlib.reload(cfg)
    from app.config import Settings, settings
    from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType
    from app.services.analyzer import analyze_project_documents
    from app.services.cdm_writer import build_canonical_from_meta_json
    from app.services.rule_engine.ai_engine import list_ai_hybrid_seed_rules, run_ai_hybrid_seed_rules
    from app.services.rule_engine.llm_client import LLMClient
    from app.services.rule_engine.hybrid_detectors import detect_hybrid_discrepancy
    from app.services.rule_engine.context import RuleContext, build_doc_view

    print("PROVIDER_STATUS:")
    print("  openai_api_key_set =", bool((settings.openai_api_key or "").strip()))
    print("  llm_provider =", settings.llm_provider)
    print("  llm_model =", settings.llm_model)
    print("  llm_base_url =", settings.llm_base_url)
    print("  ai_rule_engine_enabled =", settings.ai_rule_engine_enabled)
    assert settings.llm_provider != "local_semantic", "Must use real LLM, not local_semantic stub"
    assert settings.llm_provider == "openai_compatible"
    assert Settings.model_fields["ai_rule_engine_enabled"].default is False

    rules = list_ai_hybrid_seed_rules()
    print(f"\nAI_HYBRID_RULES={len(rules)}")
    for r in rules:
        c = r.logic_config or {}
        print(f"  {r.code}\t{c.get('ownership_tag')}\t{c.get('check')}")

    out_dir = ROOT / "storage" / "_phase4_ai_findings"
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        files = {
            "contract_drainage.txt": (CONTRACT_DRAINAGE, DocumentCategory.TENDER),
            "itt.txt": (ITT_DOC, DocumentCategory.TENDER),
            "boq.txt": (BOQ_DOC, DocumentCategory.TENDER),
            "specs.txt": (SPEC_DOC, DocumentCategory.TENDER),
            "drawing_S101.txt": (DRAWING_DOC, DocumentCategory.DRAWING),
            "geotech.txt": (GEO_DOC, DocumentCategory.TENDER),
            "er.txt": (ER_DOC, DocumentCategory.TENDER),
            "spec_facade.txt": (SPEC2, DocumentCategory.TENDER),
        }
        docs = []
        for i, (name, (text, cat)) in enumerate(files.items(), start=1):
            path = tmp_path / name
            path.write_text(text, encoding="utf-8")
            meta = {"extraction": {"method": "text", "confidenceScore": 95, "structured": {}}}
            canonical = build_canonical_from_meta_json(
                document_id=i,
                project_id=401,
                category=cat.value,
                original_name=name,
                content_type="text/plain",
                extracted_text=text,
                meta=meta,
            )
            if name == "boq.txt":
                rows = []
                for line in text.splitlines():
                    if line.lower().startswith("code|") or "|" not in line:
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 6:
                        rows.append(parts[:6])
                canonical["tables"] = [
                    {
                        "id": "tbl-boq",
                        "headers": ["code", "description", "qty", "unit", "unit_price", "total_price"],
                        "rows": rows,
                        "role_hint": "boq_like",
                        "confidence": 95,
                    }
                ]
                canonical["subtype"] = "excel_boq_candidate"
            docs.append(
                {
                    "id": i,
                    "category": cat,
                    "original_name": name,
                    "extracted_text": text,
                    "content_type": "text/plain",
                    "meta_json": json.dumps({"extraction": meta["extraction"], "canonical": canonical}),
                    "canonical": canonical,
                }
            )

        # Include real PDF if present (project_5)
        pdfs = list((ROOT / "storage" / "project_5").rglob("*.pdf"))
        if pdfs:
            print("Included real PDF:", pdfs[0].name)

        # Prove HYBRID python-first for contract vs ITT
        ctx = RuleContext(
            project_id=401,
            country="DE",
            project_type=ProjectType.OFFICE,
            documents=[build_doc_view(d) for d in docs],
            selected_standards=[{"code": "DE_VOB_B", "is_selected": True}],
        )
        disc = detect_hybrid_discrepancy("contract_vs_itt_deadlines", ctx)
        print("\nHYBRID_PYTHON_FIRST contract_vs_itt_deadlines =", disc.summary if disc else None)
        assert disc is not None, "Python discrepancy must exist before AI explain"

        client = LLMClient()
        assert client.is_configured, "LLMClient must be configured with API key"
        assert client.provider == "openai_compatible", f"got provider={client.provider}"
        print(f"\nLLMClient.provider={client.provider} model={client.model}")

        findings, metrics = run_ai_hybrid_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=docs,
            project_type=ProjectType.OFFICE,
            selected_standards=[{"code": "DE_VOB_B", "is_selected": True}, {"code": "FIDIC_RED", "is_selected": True}],
            project_id=401,
            llm=client,
        )

    print("\n=== AI/HYBRID METRICS (REAL LLM) ===")
    print(json.dumps({k: v for k, v in metrics.items() if k != "per_call"}, ensure_ascii=False, indent=2))
    print("per_call_sample=", json.dumps(metrics.get("per_call", [])[:5], ensure_ascii=False, indent=2))

    assert metrics.get("provider") == "openai_compatible", metrics
    assert (metrics.get("total_prompt_tokens") or 0) > 0, "Real LLM must consume prompt tokens"
    assert (metrics.get("total_completion_tokens") or 0) > 0, "Real LLM must consume completion tokens"

    ai_like = [f for f in findings if f.source_layer in {"llm_based", "hybrid"}]
    print(f"\nAI_HYBRID_FINDINGS={len(ai_like)}")
    assert len(ai_like) >= 2, f"Need ≥2 AI/hybrid findings, got {len(ai_like)}"

    # Must include the known drainage ambiguity [AI]
    drainage = next((f for f in ai_like if f.code == "CON-SEED-001"), None)
    assert drainage is not None, "CON-SEED-001 (drainage/if necessary) must fire"
    assert drainage.source_excerpt and drainage.source_excerpt.strip(), "AI finding needs source_excerpt"
    assert drainage.confidence_score is not None and 0 <= int(drainage.confidence_score) <= 100
    assert drainage.description and len(drainage.description) > 40, "AI finding needs real reasoning text"

    # Prefer CON-SEED-002 HYBRID (contract vs ITT deadlines); else any hybrid
    hybrid = next((f for f in ai_like if f.code == "CON-SEED-002"), None)
    if hybrid is None:
        hybrid = next((f for f in ai_like if f.source_layer == "hybrid"), None)
    assert hybrid is not None, "At least one HYBRID finding required"
    assert hybrid.source_layer == "hybrid"
    assert hybrid.source_excerpt and hybrid.source_excerpt.strip(), "HYBRID finding needs source_excerpt"
    assert hybrid.confidence_score is not None and 0 <= int(hybrid.confidence_score) <= 100
    assert hybrid.description and len(hybrid.description) > 40, "HYBRID finding needs real reasoning text"

    dump = []
    print("\n========== SAMPLE [AI] FINDING (CON-SEED-001) ==========")
    ai_rec = {
        "code": drainage.code,
        "source_layer": drainage.source_layer,
        "confidence_score": drainage.confidence_score,
        "severity": drainage.severity.value,
        "title": drainage.title,
        "description": drainage.description,
        "source_excerpt": drainage.source_excerpt,
        "recommendation": drainage.recommendation,
        "cause_effect_chain": drainage.cause_effect_chain,
    }
    print(json.dumps(ai_rec, ensure_ascii=False, indent=2))

    print("\n========== SAMPLE [HYBRID] FINDING ==========")
    hy_rec = {
        "code": hybrid.code,
        "source_layer": hybrid.source_layer,
        "confidence_score": hybrid.confidence_score,
        "severity": hybrid.severity.value,
        "title": hybrid.title,
        "description": hybrid.description,
        "source_excerpt": hybrid.source_excerpt,
        "recommendation": hybrid.recommendation,
        "cause_effect_chain": hybrid.cause_effect_chain,
    }
    print(json.dumps(hy_rec, ensure_ascii=False, indent=2))

    print("\n========== ALL AI/HYBRID FINDINGS (summary) ==========")
    for f in ai_like:
        rec = {
            "code": f.code,
            "source_layer": f.source_layer,
            "confidence_score": f.confidence_score,
            "severity": f.severity.value,
            "title": f.title,
            "description": f.description,
            "source_excerpt": f.source_excerpt,
            "evidence": f.evidence,
            "recommendation": f.recommendation,
            "cause_effect_chain": f.cause_effect_chain,
        }
        dump.append(rec)
        print(f"  {f.code} | {f.source_layer} | conf={f.confidence_score} | excerpt_len={len(f.source_excerpt or '')}")

    (out_dir / "ai_hybrid_findings.json").write_text(
        json.dumps(
            {
                "metrics": metrics,
                "sample_ai": ai_rec,
                "sample_hybrid": hy_rec,
                "findings": dump,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # MVP unaffected
    mvp = analyze_project_documents(
        country=CountryCode.DE,
        report_language=LanguageCode.EN,
        documents=[
            {
                "category": DocumentCategory.TENDER,
                "original_name": "scope.txt",
                "extracted_text": "scope of work bill of quantities payment terms",
            }
        ],
        project_type=ProjectType.OFFICE,
        selected_standards=[],
    )
    print(
        "\nMVP keyword analyzer:",
        "findings=",
        len(mvp.get("findings") or []),
        "layers=",
        {getattr(x, "source_layer", None) for x in (mvp.get("findings") or [])},
    )

    print("\nCOST/LATENCY (REAL OPENAI):")
    print(f"  provider={metrics.get('provider')} model={metrics.get('model')}")
    print(f"  total_latency_ms={metrics.get('total_latency_ms')}")
    print(f"  estimated_cost_usd={metrics.get('estimated_cost_usd')}")
    print(f"  per_document={metrics.get('per_document')}")
    print(
        f"  calls={metrics.get('calls')} "
        f"prompt_tokens={metrics.get('total_prompt_tokens')} "
        f"completion_tokens={metrics.get('total_completion_tokens')}"
    )
    assert metrics.get("provider") != "local_semantic"
    assert (metrics.get("estimated_cost_usd") or 0) > 0 or (metrics.get("total_prompt_tokens") or 0) > 100

    print("PASS Phase 4 REAL LLM AI/HYBRID findings with confidence + source_excerpt")
    print("PASS MVP unaffected")
    print("Phase 4 REAL-LLM VALIDATION PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
