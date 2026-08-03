"""Phase 3 — run [PYTHON] seed rule runners; print real Findings.

Creates 3 mini-projects with intentional deterministic defects (schedule/BOQ/tender),
optionally includes a real stored PDF from project_5, and asserts ≥3 rule_based findings.

Usage (from backend/):
  set NEW_RULE_ENGINE_ENABLED=true
  set CDM_ENABLED=true
  python scripts/phase3_python_rules_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _schedule_bad() -> str:
    # ID|Name|Start|Finish|Duration|Float|Predecessors|Resources|Milestone
    return """# programme start: 2026-03-01
ID|Name|Start|Finish|Duration|Float|Predecessors|Resources|Milestone
A100|Site setup|2026-03-01|2026-03-10|10|5||crew-A|0
A110|Foundations|2026-03-11|2026-04-01|20|-3|A100|crew-B|0
A120|Bad zero duration task|2026-04-02|2026-04-02|0|2|A110||0
A130|End before start|2026-05-10|2026-05-01| -5 |1|A110|crew-C|0
A140|Island floating activity|2026-06-01|2026-06-15|14|4|||0
A150|Structure|2026-04-05|2026-07-01|80|0|A110|crew-D|0
"""


def _contract_ntp() -> str:
    return """CONSTRUCTION CONTRACT
Employer: City Dev AG
Contractor: BuildCo
Notice to Proceed: 2026-01-15
Commencement date: 2026-01-15
Completion date: 2026-12-01
Bid deadline: 2025-12-01
"""


def _boq_math_bad() -> str:
    # code|desc|qty|unit|rate|total  — intentional math error on 0100
    return """code|description|qty|unit|unit_price|total_price
0100|Exterior wall Wall-A per drawing A-101|120|m2|50|5000
0110|Concrete footing|10|m3|100|1000
BADX|Invalid GAEB code item|1|pcs|10|10
"""


def _drawing_rev_a() -> str:
    return """Architectural Drawing A-101 Rev B
Wall-A exterior envelope unit m3
Revision: B
"""


def _drawing_rev_b() -> str:
    return """Structural Drawing S-201 Rev C
Revision: C
Wall-A noted
"""


def _itt_addenda() -> str:
    return """INSTRUCTIONS TO TENDERERS
Bid deadline: 2025-12-01
Completion date: 2026-11-01
Appendices: A, B, C
See Appendix D for forms.
Addendum No. 1 issue date: 2025-11-01
Addendum No. 3 issued: 2025-12-10
Replace item Wall-Z cladding system with alternative product.
Employer Requirements: The Contractor shall provide a BMS building management system for all floors.
"""


def _addendum3() -> str:
    return """Addendum No. 3
Issue date: 2025-12-10
Change: replace Wall-Z cladding system
"""


def _er_doc() -> str:
    return """Employer Requirements
Requirement 1: The Contractor shall provide a BMS building management system.
Requirement 2: The Contractor shall provide a helipad lighting package.
"""


def _geotech_stale() -> str:
    return """Geotechnical Report
Report date: 2018-01-15
Borehole BH-01 at site. Soil investigation completed.
Groundwater table at -3.2m. Geotechnical recommendations for foundations.
"""


def main() -> int:
    from app.config import Settings, settings
    from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType
    from app.services.analyzer import analyze_project_documents
    from app.services.cdm_writer import build_canonical_from_meta_json
    from app.services.extractor import extract_document_full
    from app.services.rule_engine import list_python_seed_rules, run_python_seed_rules
    from app.services.rule_engine.context import ElementView
    from scripts.verify_ifc_gaeb import build_minimal_ifc

    print("new_rule_engine_enabled=", settings.new_rule_engine_enabled)
    assert Settings.model_fields["new_rule_engine_enabled"].default is False

    py_rules = list_python_seed_rules()
    print(f"PYTHON_SEED_RULES={len(py_rules)}")
    for r in py_rules:
        print(f"  {r.code}\t{(r.logic_config or {}).get('check')}")

    out_dir = ROOT / "storage" / "_phase3_rule_findings"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rule_findings = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # ----- Project 1: Schedule defects + NTP mismatch -----
        sched = tmp_path / "programme.csv.txt"
        sched.write_text(_schedule_bad(), encoding="utf-8")
        contract = tmp_path / "contract.txt"
        contract.write_text(_contract_ntp(), encoding="utf-8")

        def _doc(path: Path, category: DocumentCategory, ctype: str, treat_drawing: bool = False) -> dict:
            result = extract_document_full(path, allow_ocr=False, treat_as_drawing=treat_drawing)
            # For our crafted text files, prefer file text if extractor is thin
            text = result.merged_text or path.read_text(encoding="utf-8")
            if path.suffix in {".txt"} and len(text) < len(path.read_text(encoding="utf-8")):
                text = path.read_text(encoding="utf-8")
            # Always use crafted content for deterministic schedule/boq tables
            if path.name in {
                "programme.csv.txt",
                "contract.txt",
                "boq.txt",
                "arch_A101.txt",
                "struct_S201.txt",
                "itt.txt",
                "addendum_3.txt",
                "er.txt",
                "geotech.txt",
            }:
                text = path.read_text(encoding="utf-8")
            meta = result.to_meta() if result else {"extraction": {"method": "text", "confidenceScore": 90}}
            if path.suffix == ".txt":
                meta = {
                    "extraction": {
                        "method": "text",
                        "confidenceScore": 92,
                        "structured": {},
                    }
                }
            canonical = build_canonical_from_meta_json(
                document_id=None,
                project_id=1,
                category=category.value,
                original_name=path.name,
                content_type=ctype,
                extracted_text=text,
                meta=meta,
            )
            # Inject BOQ table into CDM for pipe BOQ text
            if path.name == "boq.txt":
                rows = []
                for line in text.splitlines():
                    if "|" not in line or line.lower().startswith("code|"):
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 6:
                        rows.append(parts[:6])
                canonical["tables"] = [
                    {
                        "id": "tbl-boq",
                        "name": "BOQ",
                        "headers": ["code", "description", "qty", "unit", "unit_price", "total_price"],
                        "rows": rows,
                        "role_hint": "boq_like",
                        "confidence": 95,
                    }
                ]
                canonical["subtype"] = "excel_boq_candidate"
            return {
                "id": abs(hash(path.name)) % 100000,
                "category": category,
                "original_name": path.name,
                "extracted_text": text,
                "content_type": ctype,
                "meta_json": json.dumps({"extraction": meta.get("extraction", {}), "canonical": canonical}),
                "canonical": canonical,
            }

        p1_docs = [
            _doc(sched, DocumentCategory.SCHEDULE, "text/plain"),
            _doc(contract, DocumentCategory.TENDER, "text/plain"),
        ]
        f1 = run_python_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=p1_docs,
            project_type=ProjectType.OFFICE,
            selected_standards=[],
            project_id=101,
        )
        print(f"\n=== PROJECT 1 (schedule/contract) rule findings: {len(f1)} ===")
        all_rule_findings.extend(("P1", x) for x in f1)

        # ----- Project 2: BOQ math + IFC presence + drawing rev mismatch -----
        boq = tmp_path / "boq.txt"
        boq.write_text(_boq_math_bad(), encoding="utf-8")
        arch = tmp_path / "arch_A101.txt"
        arch.write_text(_drawing_rev_a(), encoding="utf-8")
        struct = tmp_path / "struct_S201.txt"
        struct.write_text(_drawing_rev_b(), encoding="utf-8")
        ifc_path = tmp_path / "model.ifc"
        build_minimal_ifc(ifc_path)
        ifc_result = extract_document_full(ifc_path, treat_as_drawing=True)
        ifc_meta = ifc_result.to_meta()
        ifc_can = build_canonical_from_meta_json(
            document_id=201,
            project_id=2,
            category="drawing",
            original_name=ifc_path.name,
            content_type="application/x-step",
            extracted_text=ifc_result.merged_text or "",
            meta=ifc_meta,
        )
        # Element registry: Wall-A from IFC (also in BOQ) + Wall-B only in IFC registry
        elements = [
            ElementView(
                id=1,
                element_type="Wall",
                name_label="Wall-A",
                type_mark="Wall-A",
                ifc_global_id="GUID-WALL-A",
                match_key="wall:wall-a",
                document_ids=[201],
            ),
            ElementView(
                id=2,
                element_type="Wall",
                name_label="Wall-B",
                type_mark="Wall-B",
                ifc_global_id="GUID-WALL-B",
                match_key="wall:wall-b",
                document_ids=[201],
            ),
        ]
        p2_docs = [
            _doc(boq, DocumentCategory.TENDER, "text/plain"),
            _doc(arch, DocumentCategory.DRAWING, "text/plain"),
            _doc(struct, DocumentCategory.DRAWING, "text/plain"),
            {
                "id": 201,
                "category": DocumentCategory.DRAWING,
                "original_name": ifc_path.name,
                "extracted_text": ifc_result.merged_text or "",
                "content_type": "application/x-step",
                "meta_json": json.dumps({"extraction": ifc_meta.get("extraction", {}), "canonical": ifc_can}),
                "canonical": ifc_can,
            },
        ]
        # Attach real PDF from storage if present (project_5)
        pdfs = list((ROOT / "storage" / "project_5").rglob("*.pdf"))
        if pdfs:
            pdf = pdfs[0]
            try:
                p2_docs.append(_doc(pdf, DocumentCategory.TENDER, "application/pdf"))
                print("Included real PDF:", pdf)
            except Exception as exc:  # noqa: BLE001
                print("PDF skip:", exc)

        f2 = run_python_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=p2_docs,
            project_type=ProjectType.OFFICE,
            selected_standards=[{"code": "DIN-EN-1992", "is_selected": True, "is_current": False, "newer_version": "2023"}],
            elements=elements,
            project_id=102,
            standard_versions={"DIN-EN-1992": {"is_current": False, "newer_version": "2023"}},
        )
        print(f"\n=== PROJECT 2 (BOQ/drawings/IFC) rule findings: {len(f2)} ===")
        all_rule_findings.extend(("P2", x) for x in f2)

        # ----- Project 3: tender completeness / addenda / geotech / ER -----
        itt = tmp_path / "itt.txt"
        itt.write_text(_itt_addenda(), encoding="utf-8")
        add3 = tmp_path / "addendum_3.txt"
        add3.write_text(_addendum3(), encoding="utf-8")
        er = tmp_path / "er.txt"
        er.write_text(_er_doc(), encoding="utf-8")
        geo = tmp_path / "geotech.txt"
        geo.write_text(_geotech_stale(), encoding="utf-8")
        # Bridge project: geotech required; stale report present; addenda 1+3 gap; ER unfunded
        p3_docs = [
            _doc(itt, DocumentCategory.TENDER, "text/plain"),
            _doc(add3, DocumentCategory.TENDER, "text/plain"),
            _doc(er, DocumentCategory.TENDER, "text/plain"),
            _doc(geo, DocumentCategory.TENDER, "text/plain"),
            _doc(boq, DocumentCategory.TENDER, "text/plain"),
            _doc(sched, DocumentCategory.SCHEDULE, "text/plain"),
        ]
        f3 = run_python_seed_rules(
            country=CountryCode.DE,
            report_language=LanguageCode.EN,
            documents=p3_docs,
            project_type=ProjectType.BRIDGE,
            selected_standards=[],  # trigger mandatory missing
            project_id=103,
        )
        print(f"\n=== PROJECT 3 (tender/addenda/geotech/ER) rule findings: {len(f3)} ===")
        all_rule_findings.extend(("P3", x) for x in f3)

    # Print at least 3 real findings in full
    print("\n========== ACTUAL RULE-BASED FINDINGS (sample) ==========")
    shown = []
    for proj, f in all_rule_findings:
        if f.source_layer != "rule_based":
            continue
        shown.append((proj, f))
    assert len(shown) >= 3, f"Expected ≥3 rule findings, got {len(shown)}"

    dump = []
    for proj, f in shown[:12]:
        rec = {
            "project": proj,
            "code": f.code,
            "source_layer": f.source_layer,
            "severity": f.severity.value,
            "title": f.title,
            "description": f.description,
            "evidence": f.evidence,
            "risk_score": f.risk_score,
            "cause_effect_chain": f.cause_effect_chain,
        }
        dump.append(rec)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        print("---")

    (out_dir / "python_rule_findings.json").write_text(
        json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # MVP keyword analyzer still works with flag conceptually separate
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
        "status=",
        mvp.get("analysis_status") or "completed",
        "findings=",
        len(mvp.get("findings") or []),
        "engine=",
        mvp.get("engine"),
    )
    # Ensure keyword findings are not source_layer=rule_based
    kw_layers = {getattr(x, "source_layer", None) for x in (mvp.get("findings") or [])}
    assert None in kw_layers or not any(x == "rule_based" for x in kw_layers)

    # Coverage: every PYTHON check has a runner
    from app.services.rule_engine.runners import CHECK_RUNNERS

    missing_runners = [
        (r.code, (r.logic_config or {}).get("check"))
        for r in py_rules
        if (r.logic_config or {}).get("check") not in CHECK_RUNNERS
    ]
    assert not missing_runners, f"Missing runners: {missing_runners}"

    codes = {f.code for _, f in shown}
    print(f"\nUnique rule codes fired: {sorted(codes)}")
    print(f"TOTAL_RULE_FINDINGS={len(shown)}")
    print("PASS Phase 3 PYTHON runners produce real Findings")
    print("PASS MVP keyword analyzer unaffected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
