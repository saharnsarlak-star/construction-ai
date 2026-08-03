"""Phase 1 CDM writer test — real PDF + IFC + GAEB. Prints actual JSON.

Usage (from backend/):
  set CDM_ENABLED=true
  python scripts/phase1_cdm_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _print_cdm(label: str, canonical: dict, out_path: Path | None = None) -> None:
    print(f"\n{'=' * 72}")
    print(label)
    print("=" * 72)
    # Compact summary + full JSON (ASCII-safe for Windows consoles)
    print(
        "SUMMARY:",
        json.dumps(
            {
                "subtype": canonical.get("subtype"),
                "method": (canonical.get("extraction") or {}).get("method"),
                "confidence": (canonical.get("extraction") or {}).get("confidence_score"),
                "content_units": len(canonical.get("content_units") or []),
                "tables": len(canonical.get("tables") or []),
                "has_spatial": canonical.get("spatial") is not None,
                "has_quantities": canonical.get("quantities_summary") is not None,
                "language_primary": canonical.get("language_primary"),
                "title": (canonical.get("identity") or {}).get("title"),
            },
            ensure_ascii=True,
        ),
    )
    full = json.dumps(canonical, ensure_ascii=False, indent=2)
    if out_path is not None:
        out_path.write_text(full, encoding="utf-8")
        print(f"FULL_CDM_JSON_WRITTEN={out_path}")
    print("FULL_CDM_JSON:")
    # Prefer readable console dump; escape non-ASCII if needed
    try:
        print(full[:12000])
    except UnicodeEncodeError:
        print(json.dumps(canonical, ensure_ascii=True, indent=2)[:12000])
    if len(full) > 12000:
        print("... [truncated for display] ...")


def main() -> int:
    from app.config import settings
    from app.services.cdm_writer import build_canonical_from_meta_json
    from app.services.extractor import extract_document_full, merge_extraction_meta
    from app.services.analyzer import analyze_project_documents
    from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType
    from scripts.verify_ifc_gaeb import build_minimal_gaeb_x83, build_minimal_ifc

    print("cdm_enabled setting =", settings.cdm_enabled)

    # --- Real PDF from local storage (if present) ---
    pdf_candidates = list((ROOT / "storage").glob("project_*/tender/*.pdf"))
    pdf_candidates += list((ROOT / "storage").glob("project_*/standard/*.pdf"))
    if not pdf_candidates:
        # fallback tiny PDF
        pdf_path = ROOT / "storage" / "_phase1_sample.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(
            b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
            + b"\nBT /F1 12 Tf 100 700 Td (Contract Clause 1.1 Notice period 14 days) Tj ET\n"
        )
    else:
        pdf_path = pdf_candidates[0]
    print("PDF_PATH=", pdf_path)

    pdf_result = extract_document_full(pdf_path, allow_ocr=True, treat_as_drawing=False)
    pdf_meta = pdf_result.to_meta()
    pdf_cdm = build_canonical_from_meta_json(
        document_id=9001,
        project_id=5,
        category="tender",
        original_name=pdf_path.name,
        content_type="application/pdf",
        extracted_text=pdf_result.merged_text or "",
        meta=pdf_meta,
    )
    out_dir = ROOT / "storage" / "_phase1_cdm_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    _print_cdm(f"CDM for PDF: {pdf_path.name}", pdf_cdm, out_dir / "cdm_pdf.json")

    # --- IFC + GAEB (generated real extractors) ---
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ifc_path = tmp_path / "phase1.ifc"
        gaeb_path = tmp_path / "phase1.X83"
        build_minimal_ifc(ifc_path)
        build_minimal_gaeb_x83(gaeb_path)

        ifc_result = extract_document_full(ifc_path, treat_as_drawing=True)
        ifc_meta = ifc_result.to_meta()
        ifc_cdm = build_canonical_from_meta_json(
            document_id=9002,
            project_id=5,
            category="drawing",
            original_name=ifc_path.name,
            content_type="application/x-step",
            extracted_text=ifc_result.merged_text or "",
            meta=ifc_meta,
        )
        _print_cdm("CDM for IFC", ifc_cdm, out_dir / "cdm_ifc.json")

        gaeb_result = extract_document_full(gaeb_path, treat_as_drawing=False)
        gaeb_meta = gaeb_result.to_meta()
        gaeb_cdm = build_canonical_from_meta_json(
            document_id=9003,
            project_id=5,
            category="tender",
            original_name=gaeb_path.name,
            content_type="application/xml",
            extracted_text=gaeb_result.merged_text or "",
            meta=gaeb_meta,
        )
        _print_cdm("CDM for GAEB X83", gaeb_cdm, out_dir / "cdm_gaeb.json")

        # merge_extraction_meta must keep extraction when adding canonical
        merged = merge_extraction_meta(
            json.dumps(gaeb_meta, ensure_ascii=False),
            {"canonical": gaeb_cdm},
        )
        merged_obj = json.loads(merged)
        assert "extraction" in merged_obj, "extraction wiped"
        assert "canonical" in merged_obj, "canonical missing"
        assert merged_obj["extraction"].get("method") == "gaeb_native"
        print("\nPASS merge_extraction_meta keeps extraction + adds canonical")

    # MVP analyzer still works on extracted_text (no CDM required)
    analysis = analyze_project_documents(
        country=CountryCode.IR,
        report_language=LanguageCode.EN,
        documents=[
            {
                "category": DocumentCategory.TENDER,
                "original_name": pdf_path.name,
                "extracted_text": pdf_result.merged_text or "scope of work bill of quantities",
            }
        ],
        project_type=ProjectType.OFFICE,
        selected_standards=[],
    )
    print("\nMVP analyzer status=", analysis.get("analysis_status") or "completed")
    print("MVP findings_count=", len(analysis.get("findings") or []))
    print("MVP readiness=", analysis.get("readiness_score"))
    print("PASS keyword MVP analyzer still runs")

    # Structural asserts for CDM
    assert pdf_cdm["subtype"]
    assert ifc_cdm["subtype"] == "ifc_model"
    assert gaeb_cdm["subtype"] == "gaeb_lv"
    assert gaeb_cdm.get("tables")
    assert ifc_cdm.get("spatial") is not None
    print("\nALL PHASE1 CDM CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
