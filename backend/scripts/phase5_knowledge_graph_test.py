"""Phase 5 — Knowledge Graph related_findings_chain on Wall-A cross-docs.

Reuses Phase 2 pattern: IFC + GAEB BOQ + Contract all reference Wall-A.
Creates Findings on each document side, links via Element Registry / OntologyEdge,
prints the actual multi-hop chain narrative.

Usage (from backend/):
  set KNOWLEDGE_GRAPH_ENABLED=true
  set ONTOLOGY_ENABLED=true
  set CDM_ENABLED=true
  python scripts/phase5_knowledge_graph_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _gaeb_wall_a(path: Path) -> None:
    from scripts.phase2_ontology_test import _build_phase2_gaeb

    _build_phase2_gaeb(path)


def _contract_wall_a(path: Path) -> None:
    path.write_text(
        """CONSTRUCTION CONTRACT
Employer: Acme Development GmbH
Contractor: BuildRight Contracting Ltd

Clause 5.2 — Exterior Envelope
The Contractor shall construct the exterior wall Wall-A as shown on drawing A-101
and as quantified in the Bill of Quantities. Wall-A shall achieve fire rating REI 90.
Responsibility for Wall-A waterproofing shall be agreed later if necessary.
""",
        encoding="utf-8",
    )


def _schedule_wall_a(path: Path) -> None:
    path.write_text(
        """# programme mentioning Wall-A envelope
ID|Name|Start|Finish|Duration|Float|Predecessors|Resources|Milestone
A100|Site setup|2026-03-01|2026-03-10|10|5||crew-A|0
A200|Wall-A exterior envelope|2026-03-11|2026-04-01|0| -2 |A100||0
A300|Handover|2026-04-02|2026-04-02|0|0|A200||1
""",
        encoding="utf-8",
    )


async def _run() -> int:
    from sqlalchemy import select

    from app.config import Settings, settings
    from app.database import SessionLocal, init_db
    from app.models import (
        Analysis,
        CountryCode,
        Document,
        DocumentCategory,
        Finding,
        LanguageCode,
        Project,
        ProjectElement,
        ProjectType,
        RiskSeverity,
    )
    from app.services.analyzer import analyze_project_documents
    from app.services.cdm_writer import build_canonical_from_meta_json
    from app.services.extractor import extract_document_full, merge_extraction_meta
    from app.services.knowledge_graph import build_chains_for_analysis
    from app.services.ontology_writer import ingest_document_ontology
    from scripts.verify_ifc_gaeb import build_minimal_ifc

    print("knowledge_graph_enabled=", settings.knowledge_graph_enabled)
    assert Settings.model_fields["knowledge_graph_enabled"].default is False

    await init_db()
    out_dir = ROOT / "storage" / "_phase5_kg_samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ifc_path = tmp_path / "phase5_wall.ifc"
        gaeb_path = tmp_path / "phase5_boq.X83"
        contract_path = tmp_path / "phase5_contract.txt"
        schedule_path = tmp_path / "phase5_schedule.txt"
        build_minimal_ifc(ifc_path)
        _gaeb_wall_a(gaeb_path)
        _contract_wall_a(contract_path)
        _schedule_wall_a(schedule_path)

        specs = [
            (ifc_path, DocumentCategory.DRAWING, "application/x-step", True),
            (gaeb_path, DocumentCategory.TENDER, "application/xml", False),
            (contract_path, DocumentCategory.TENDER, "text/plain", False),
            (schedule_path, DocumentCategory.SCHEDULE, "text/plain", False),
        ]

        async with SessionLocal() as db:
            project = Project(
                name="Phase5 Knowledge Graph Wall-A",
                country=CountryCode.DE,
                project_type=ProjectType.OFFICE.value,
                ui_language=LanguageCode.EN,
                report_language=LanguageCode.EN,
            )
            db.add(project)
            await db.flush()

            docs: list[Document] = []
            for path, category, ctype, as_drawing in specs:
                result = extract_document_full(path, allow_ocr=False, treat_as_drawing=as_drawing)
                text = result.merged_text or ""
                if path.suffix == ".txt":
                    text = path.read_text(encoding="utf-8")
                meta = result.to_meta() if path.suffix != ".txt" else {
                    "extraction": {"method": "text", "confidenceScore": 95, "structured": {}}
                }
                if path.suffix == ".txt":
                    meta = {"extraction": {"method": "text", "confidenceScore": 95, "structured": {}}}
                canonical = build_canonical_from_meta_json(
                    document_id=None,
                    project_id=project.id,
                    category=category.value,
                    original_name=path.name,
                    content_type=ctype,
                    extracted_text=text,
                    meta=meta,
                )
                doc = Document(
                    project_id=project.id,
                    category=category,
                    original_name=path.name,
                    stored_path=str(path),
                    content_type=ctype,
                    size_bytes=path.stat().st_size,
                    extracted_text=text,
                    meta_json=merge_extraction_meta(
                        json.dumps(meta, ensure_ascii=False),
                        {"canonical": canonical},
                    ),
                )
                db.add(doc)
                await db.flush()
                can = json.loads(doc.meta_json or "{}").get("canonical") or canonical
                can["document_id"] = doc.id
                doc.meta_json = merge_extraction_meta(doc.meta_json, {"canonical": can})
                await ingest_document_ontology(db, document=doc, canonical=can, meta=json.loads(doc.meta_json or "{}"))
                docs.append(doc)

            # Shared Wall-A element must exist
            elements = (
                await db.execute(
                    select(ProjectElement).where(ProjectElement.project_id == project.id)
                )
            ).scalars().all()
            wall = next(
                (
                    e
                    for e in elements
                    if (e.type_mark or "").lower() == "wall-a"
                    or (e.name_label or "").lower() == "wall-a"
                    or (e.match_key or "").endswith("wall-a")
                ),
                None,
            )
            assert wall is not None, f"Wall-A missing from registry: {elements}"
            print("SHARED_ELEMENT", wall.id, wall.match_key, wall.ifc_global_id)

            analysis = Analysis(
                project_id=project.id,
                status="completed",
                summary="Phase5 KG test analysis",
                report_language=LanguageCode.EN,
                result_json=json.dumps({"readiness_score": 70, "counts": {"high": 3, "medium": 0, "low": 0, "total": 3}}),
            )
            db.add(analysis)
            await db.flush()

            # Findings on BOQ / Contract / Schedule / Drawing — all reference Wall-A
            finding_specs = [
                (
                    "BOQ-SEED-002",
                    "cost",
                    "Item on Drawing absent in BOQ (or vice versa)",
                    f"Wall-A from IFC/drawing may lack full BOQ coverage. Element Wall-A ({wall.match_key}).",
                    f"Wall-A exterior masonry referenced in {docs[1].original_name} and IFC.",
                    docs[1].id,
                    docs[1].original_name,
                ),
                (
                    "CON-SEED-001",
                    "claim",
                    "Ambiguous Employer vs Contractor responsibility for Wall-A",
                    "Clause uses 'if necessary' for Wall-A waterproofing responsibility.",
                    f"Wall-A waterproofing shall be agreed later if necessary. ({docs[2].original_name})",
                    docs[2].id,
                    docs[2].original_name,
                ),
                (
                    "SCH-SEED-002",
                    "delay",
                    "Zero duration on Wall-A exterior envelope activity",
                    "Activity A200 Wall-A exterior envelope has duration=0.0.",
                    f"A200|Wall-A exterior envelope|...|0 ({docs[3].original_name})",
                    docs[3].id,
                    docs[3].original_name,
                ),
                (
                    "DRAW-SEED-001",
                    "claim",
                    "Drawing revision risk near Wall-A",
                    f"IFC/drawing set for Wall-A ({docs[0].original_name}) needs revision alignment.",
                    f"Wall-A REI 90 on {docs[0].original_name}",
                    docs[0].id,
                    docs[0].original_name,
                ),
            ]
            for code, cat, title, desc, evidence, _did, _name in finding_specs:
                db.add(
                    Finding(
                        analysis_id=analysis.id,
                        code=code,
                        category=cat,
                        severity=RiskSeverity.HIGH,
                        title=title,
                        description=desc,
                        recommendation="Clarify Wall-A scope/responsibility/schedule before award.",
                        evidence=evidence,
                        source_excerpt=evidence[:400],
                        finding_category="risk",
                        risk_score=80,
                        source_layer="rule_based",
                        cause_effect_json=json.dumps(
                            [
                                f"element=Wall-A",
                                f"match_key={wall.match_key}",
                                f"document={_name}",
                                f"document_id={_did}",
                            ]
                        ),
                    )
                )
            await db.flush()

            kg = await build_chains_for_analysis(
                db,
                project_id=project.id,
                analysis_id=analysis.id,
                documents=docs,
            )
            chains = kg["related_findings_chain"]
            payload = json.loads(analysis.result_json or "{}")
            payload["related_findings_chain"] = chains
            payload["knowledge_graph"] = {"enabled": True, "chain_count": len(chains), "link_stats": kg["link_stats"]}
            analysis.result_json = json.dumps(payload, ensure_ascii=False)
            await db.commit()

            print("\nLINK_STATS", json.dumps(kg["link_stats"], ensure_ascii=False, indent=2))
            print(f"CHAIN_COUNT={len(chains)}")
            assert len(chains) >= 1, "Expected at least one related_findings_chain"

            # Prefer the densest Wall-A chain
            wall_chains = [
                c
                for c in chains
                if (c.get("shared_element") or {}).get("id") == wall.id
                or str((c.get("shared_element") or {}).get("type_mark") or "").lower() == "wall-a"
            ]
            assert wall_chains, "No chain anchored on Wall-A"
            best = max(wall_chains, key=lambda c: c.get("hop_count") or 0)
            assert best["hop_count"] >= 2, f"Need multi-hop, got {best['hop_count']}"

            print("\n========== ACTUAL MULTI-HOP RISK CHAIN ==========")
            print(json.dumps(best, ensure_ascii=False, indent=2))
            (out_dir / "related_findings_chain.json").write_text(
                json.dumps({"all_chains": chains, "best": best}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("\nNARRATIVE:")
            print(best["narrative"])

            # MVP analyzer still works
            mvp = analyze_project_documents(
                country=CountryCode.DE,
                report_language=LanguageCode.EN,
                documents=[
                    {
                        "category": DocumentCategory.TENDER,
                        "original_name": "scope.txt",
                        "extracted_text": "scope of work bill of quantities",
                    }
                ],
                project_type=ProjectType.OFFICE,
                selected_standards=[],
            )
            print("\nMVP findings=", len(mvp.get("findings") or []))
            print("PASS Phase 5 related_findings_chain on shared Wall-A")
            print("PASS MVP unaffected")
            return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
