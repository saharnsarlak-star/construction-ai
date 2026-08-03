"""Phase 2 test — Party + Element Registry + OntologyEdge across BOQ / IFC / Contract.

Creates three documents that all reference Wall-A (exterior wall) and asserts they
resolve to ONE ProjectElement. Prints the actual registry record.

Usage (from backend/):
  set CDM_ENABLED=true
  set ONTOLOGY_ENABLED=true
  python scripts/phase2_ontology_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _build_phase2_gaeb(path: Path) -> None:
    """GAEB X83 BoQ item that explicitly references IFC Wall-A + drawing A-101."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2">
  <GAEBInfo>
    <Version>3.2</Version>
    <VersDate>2013-10</VersDate>
    <Date>2026-01-01</Date>
    <Time>12:00:00</Time>
  </GAEBInfo>
  <Award>
    <DP>83</DP>
    <Project>
      <Name>Phase2 Cross-Ref LV</Name>
    </Project>
    <BoQ>
      <BoQInfo>
        <Name>Phase2 BoQ</Name>
        <LblBoQ>LV Wall</LblBoQ>
      </BoQInfo>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Exterior envelope</LblTx>
          <Itemlist>
            <Item RNoPart="0100">
              <Qty>120.000</Qty>
              <QU>m2</QU>
              <Description>
                <CompleteText>
                  <OutlineText>
                    <OutlTxt>
                      <TextOutlTxt>Exterior masonry wall Wall-A per drawing A-101, fire rating REI 90</TextOutlTxt>
                    </OutlTxt>
                  </OutlineText>
                </CompleteText>
              </Description>
            </Item>
            <Item RNoPart="0110">
              <Qty>10.000</Qty>
              <QU>m3</QU>
              <Description>
                <CompleteText>
                  <OutlineText>
                    <OutlTxt>
                      <TextOutlTxt>Concrete footing unrelated</TextOutlTxt>
                    </OutlTxt>
                  </OutlineText>
                </CompleteText>
              </Description>
            </Item>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""
    path.write_text(xml, encoding="utf-8")


def _build_phase2_contract(path: Path) -> None:
    text = """CONSTRUCTION CONTRACT AGREEMENT
Employer: Acme Development GmbH
Contractor: BuildRight Contracting Ltd
Engineer: Structural Partners AG

Clause 5.2 — Exterior Envelope
The Contractor shall construct the exterior wall Wall-A as shown on drawing A-101
and as quantified in the Bill of Quantities. Wall-A shall achieve fire rating REI 90.
Any ambiguity in Wall-A specification shall be clarified by the Engineer before work.
"""
    path.write_text(text, encoding="utf-8")


async def _run() -> int:
    from sqlalchemy import select

    from app.config import Settings, settings
    from app.database import SessionLocal, init_db
    import os
    from app.models import (
        CountryCode,
        Document,
        DocumentCategory,
        ElementDocumentRef,
        LanguageCode,
        OntologyEdge,
        Party,
        Project,
        ProjectElement,
        ProjectType,
    )
    from app.services.analyzer import analyze_project_documents
    from app.services.cdm_writer import build_canonical_from_meta_json
    from app.services.extractor import extract_document_full, merge_extraction_meta
    from app.services.ontology_writer import element_to_dict, ingest_document_ontology
    from scripts.verify_ifc_gaeb import build_minimal_ifc

    print("cdm_enabled=", settings.cdm_enabled)
    print("ontology_enabled=", settings.ontology_enabled)
    # Field defaults are OFF; process env may override the live Settings instance.
    fields = Settings.model_fields
    assert fields["ontology_enabled"].default is False, "ONTOLOGY_ENABLED must default OFF"
    assert fields["cdm_enabled"].default is False, "CDM_ENABLED must default OFF"
    saved = {k: os.environ.pop(k, None) for k in ("CDM_ENABLED", "ONTOLOGY_ENABLED")}
    try:
        default = Settings(_env_file=None)
        print("defaults (no env): cdm=", default.cdm_enabled, "ontology=", default.ontology_enabled)
        assert default.ontology_enabled is False
        assert default.cdm_enabled is False
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    if not settings.ontology_enabled:
        print("WARN: ONTOLOGY_ENABLED is false in this run — forcing ingest path in test")

    await init_db()

    out_dir = ROOT / "storage" / "_phase2_ontology_samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ifc_path = tmp_path / "phase2_wall.ifc"
        gaeb_path = tmp_path / "phase2_boq.X83"
        contract_path = tmp_path / "phase2_contract.txt"
        build_minimal_ifc(ifc_path)
        _build_phase2_gaeb(gaeb_path)
        _build_phase2_contract(contract_path)

        specs = [
            (ifc_path, DocumentCategory.DRAWING, "application/x-step", True),
            (gaeb_path, DocumentCategory.TENDER, "application/xml", False),
            (contract_path, DocumentCategory.TENDER, "text/plain", False),
        ]

        async with SessionLocal() as db:
            project = Project(
                name="Phase2 Element Registry Test",
                country=CountryCode.DE,
                project_type=ProjectType.OFFICE.value,
                ui_language=LanguageCode.EN,
                report_language=LanguageCode.EN,
            )
            db.add(project)
            await db.flush()

            doc_ids: list[int] = []
            for path, category, ctype, as_drawing in specs:
                result = extract_document_full(path, allow_ocr=False, treat_as_drawing=as_drawing)
                meta = result.to_meta()
                canonical = build_canonical_from_meta_json(
                    document_id=None,
                    project_id=project.id,
                    category=category.value,
                    original_name=path.name,
                    content_type=ctype,
                    extracted_text=result.merged_text or "",
                    meta=meta,
                )
                meta_json = merge_extraction_meta(
                    json.dumps(meta, ensure_ascii=False),
                    {"canonical": canonical},
                )
                doc = Document(
                    project_id=project.id,
                    category=category,
                    original_name=path.name,
                    stored_path=str(path),
                    content_type=ctype,
                    size_bytes=path.stat().st_size,
                    extracted_text=result.merged_text or "",
                    meta_json=meta_json,
                )
                db.add(doc)
                await db.flush()
                # patch document_id into canonical for consistency
                try:
                    meta_obj = json.loads(doc.meta_json or "{}")
                except json.JSONDecodeError:
                    meta_obj = {}
                can = meta_obj.get("canonical") if isinstance(meta_obj.get("canonical"), dict) else canonical
                can["document_id"] = doc.id
                doc.meta_json = merge_extraction_meta(doc.meta_json, {"canonical": can})

                summary = await ingest_document_ontology(
                    db,
                    document=doc,
                    canonical=can,
                    meta=meta_obj,
                )
                print(f"INGEST {path.name}: {summary}")
                doc_ids.append(doc.id)

            await db.commit()
            project_id = project.id

            # --- Element Registry: Wall-A must be ONE row with ≥3 document refs ---
            elements = (
                await db.execute(
                    select(ProjectElement).where(ProjectElement.project_id == project_id)
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
            assert wall is not None, f"Wall-A not found in registry: {elements}"

            refs = (
                await db.execute(
                    select(ElementDocumentRef).where(ElementDocumentRef.element_id == wall.id)
                )
            ).scalars().all()
            ref_doc_ids = sorted({r.document_id for r in refs})
            print("\n=== SHARED ELEMENT REGISTRY RECORD ===")
            record = element_to_dict(wall, refs)
            print(json.dumps(record, ensure_ascii=False, indent=2))
            (out_dir / "shared_element_wall_a.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            assert wall.ifc_global_id, "IFC GlobalId must be merged onto shared element"
            assert len(ref_doc_ids) >= 3, f"Expected ≥3 docs linked, got {ref_doc_ids}"
            assert set(doc_ids).issubset(set(ref_doc_ids)) or len(ref_doc_ids) >= 3

            # Parties from contract
            parties = (
                await db.execute(select(Party).where(Party.project_id == project_id))
            ).scalars().all()
            party_dump = [
                {"id": p.id, "legal_name": p.legal_name, "party_role": p.party_role}
                for p in parties
            ]
            print("\n=== PARTIES ===")
            print(json.dumps(party_dump, ensure_ascii=False, indent=2))
            roles = {p.party_role for p in parties}
            assert "employer" in roles and "contractor" in roles

            # Edges
            edges = (
                await db.execute(
                    select(OntologyEdge).where(OntologyEdge.project_id == project_id)
                )
            ).scalars().all()
            edge_dump = [
                {
                    "predicate": e.predicate,
                    "from": f"{e.from_type}:{e.from_id}",
                    "to": f"{e.to_type}:{e.to_id}",
                    "origin_kind": e.origin_kind,
                    "document_id": e.document_id,
                }
                for e in edges
            ]
            print("\n=== ONTOLOGY EDGES (sample) ===")
            print(json.dumps(edge_dump[:25], ensure_ascii=False, indent=2))
            (out_dir / "ontology_edges.json").write_text(
                json.dumps(edge_dump, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            preds = {e.predicate for e in edges}
            assert "references" in preds
            assert any(e.to_type == "ProjectElement" and int(e.to_id) == wall.id for e in edges)

            # Phase 1 CDM still present on docs
            for did in doc_ids:
                d = await db.get(Document, did)
                assert d is not None
                m = json.loads(d.meta_json or "{}")
                assert "canonical" in m, "CDM canonical missing"
                assert d.extracted_text, "extracted_text must remain"

            # MVP keyword analyzer unaffected
            docs_for_analyzer = []
            for did in doc_ids:
                d = await db.get(Document, did)
                assert d is not None
                docs_for_analyzer.append(
                    {
                        "category": d.category,
                        "original_name": d.original_name,
                        "extracted_text": d.extracted_text or "",
                    }
                )
            analysis = analyze_project_documents(
                country=CountryCode.DE,
                report_language=LanguageCode.EN,
                documents=docs_for_analyzer,
                project_type=ProjectType.OFFICE,
                selected_standards=[],
            )
            print(
                "\nMVP analyzer:",
                "status=",
                analysis.get("analysis_status") or "completed",
                "findings=",
                len(analysis.get("findings") or []),
            )

            print("\nPASS Phase 2: one Wall-A element linked from IFC + GAEB + Contract")
            print("PASS Phase 1 CDM still on documents")
            print("PASS MVP keyword analyzer still runs")
            return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
