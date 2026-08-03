"""Phase 8 — Vision drawing checks + GAEB 90 fixed-width parsing.

Usage (from backend/):
  python scripts/phase8_vision_gaeb90_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "phase8"


async def _run() -> int:
    from app.config import Settings, settings
    from app.database import SessionLocal, init_db
    from app.models import (
        CountryCode,
        Document,
        DocumentCategory,
        LanguageCode,
        Project,
        ProjectType,
    )
    from app.services.gaeb90_parser import extract_gaeb90, looks_like_gaeb90
    from app.services.gaeb_extractor import extract_gaeb
    from app.services.vision_drawing_checks import (
        rasterize_drawing_pages,
        run_vision_drawing_checks,
    )

    # Ensure fixtures exist
    sys.path.insert(0, str(FIXTURE_DIR))
    from build_fixtures import write_drawing_pdf, write_gaeb90_d83

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    d83 = write_gaeb90_d83(FIXTURE_DIR / "sample_gaeb90.d83")
    pdf = write_drawing_pdf(FIXTURE_DIR / "sample_drawing_sheet.pdf")

    print("=== Phase 8 Vision + GAEB90 test ===")
    code = Settings(_env_file=None)
    print(f"code default vision_drawing_checks_enabled={code.vision_drawing_checks_enabled}")
    print(f"code default gaeb90_enabled={code.gaeb90_enabled}")
    assert code.vision_drawing_checks_enabled is False
    assert code.gaeb90_enabled is False

    # --- GAEB 90 ---
    assert looks_like_gaeb90(d83), "fixture should sniff as GAEB 90"
    print(f"\nGAEB90 sniff OK: {d83.name} size={d83.stat().st_size}")

    settings.gaeb90_enabled = False
    disabled = extract_gaeb(d83)
    print(f"Flag OFF extract_gaeb method={disabled.extraction_method} err={disabled.error}")
    assert disabled.error and "GAEB90_ENABLED" in (disabled.error or "")

    settings.gaeb90_enabled = True
    parsed = extract_gaeb(d83)
    print(
        f"Flag ON extract_gaeb method={parsed.extraction_method} "
        f"items={parsed.structured.get('item_count')} conf={parsed.confidence_score}"
    )
    assert parsed.extraction_method == "gaeb90_fixed"
    assert int(parsed.structured.get("item_count") or 0) >= 3, parsed.structured
    sample_items = (parsed.structured.get("items") or [])[:3]
    for it in sample_items:
        print(f"  item code={it.get('code')} qty={it.get('qty')} unit={it.get('unit')} desc={str(it.get('description') or '')[:50]}")
    assert any(it.get("qty") for it in sample_items)
    assert "GAEB90" in (parsed.merged_text or "") or "gaeb90" in (parsed.merged_text or "").lower()

    direct = extract_gaeb90(d83)
    assert direct.structured.get("item_count") == parsed.structured.get("item_count")

    # --- Vision drawing ---
    settings.vision_drawing_checks_enabled = False
    empty, meta_off = run_vision_drawing_checks(
        drawing_docs=[{"stored_path": str(pdf), "original_name": pdf.name, "extracted_text": ""}],
    )
    print(f"\nVision flag OFF findings={len(empty)} enabled={meta_off.get('enabled')}")
    assert empty == [] and meta_off.get("enabled") is False

    settings.vision_drawing_checks_enabled = True
    pages = rasterize_drawing_pages(pdf, max_pages=1)
    print(f"Rasterized pages={len(pages)} size={pages[0].width}x{pages[0].height}" if pages else "Rasterized pages=0")
    assert pages, "pypdfium2 should rasterize the fixture PDF"

    # Seed extracted_text with the same content so heuristics work even if OCR is weak
    fixture_text = (
        "ENGINEERING DRAWING Sheet A-101 Scale: 1:75 SCALE 1:100 "
        "PLAN VIEW Level +3.20 FFL Wall-A 12.50 m "
        "SECTION A-A Level +2.80 FFL Plan conflicts with section "
        "STEEL CONNECTION connection TBD Missing execution detail for critical junction"
    )
    findings, meta = run_vision_drawing_checks(
        drawing_docs=[
            {
                "stored_path": str(pdf),
                "original_name": pdf.name,
                "extracted_text": fixture_text,
                "category": "drawing",
            }
        ],
        report_language=LanguageCode.EN,
    )
    print(f"Vision flag ON findings={len(findings)} metrics={json.dumps({k: meta[k] for k in meta if k != 'usage'})}")
    for f in findings:
        print(f"  {f.code} | layer={f.source_layer} | conf={f.confidence_score}")
        print(f"    title={f.title}")
        assert f.source_layer == "vision_based"
        assert "[Vision]" in f.title or "VISION-BASED" in f.description
    codes = {f.code for f in findings}
    assert "DRAW-SEED-002" in codes, f"expected scale check, got {codes}"
    assert "DRAW-SEED-003" in codes, f"expected missing detail, got {codes}"
    assert "DRAW-SEED-004" in codes, f"expected plan/section, got {codes}"

    # End-to-end analyze with vision on
    await init_db()
    async with SessionLocal() as db:
        project = Project(
            name="Phase8 Vision Drawing Test",
            country=CountryCode.DE,
            project_type=ProjectType.HOSPITAL,
            ui_language=LanguageCode.EN,
            report_language=LanguageCode.EN,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)

        # Copy PDF into temp so stored_path is stable
        tmp = Path(tempfile.gettempdir()) / f"phase8_drawing_{project.id}.pdf"
        tmp.write_bytes(pdf.read_bytes())
        doc = Document(
            project_id=project.id,
            category=DocumentCategory.DRAWING,
            original_name=pdf.name,
            stored_path=str(tmp),
            content_type="application/pdf",
            size_bytes=tmp.stat().st_size,
            extracted_text=fixture_text,
            meta_json=json.dumps({"extraction": {"method": "text", "confidenceScore": 80}}),
        )
        db.add(doc)
        await db.commit()
        project_id = project.id

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # settings.vision already True
    ar = client.post(
        f"/api/projects/{project_id}/analyze",
        json={"report_language": "en"},
    )
    print(f"\nPOST analyze → {ar.status_code}")
    assert ar.status_code == 200, ar.text
    payload = ar.json()
    vision_out = [
        f
        for f in (payload.get("findings") or [])
        if f.get("source_layer") == "vision_based" or str(f.get("code") or "").startswith("DRAW-SEED-00")
    ]
    # Prefer source_layer filter
    vision_out = [f for f in (payload.get("findings") or []) if f.get("source_layer") == "vision_based"]
    print(f"analysis vision findings={len(vision_out)}")
    for f in vision_out:
        print(f"  SURFACED {f.get('code')}: {f.get('title')}")
    assert len(vision_out) >= 2, "expected vision findings in analysis"

    # Reset flags
    settings.vision_drawing_checks_enabled = False
    settings.gaeb90_enabled = False

    print(
        "\nPHASE 8 PASS: GAEB 90 parsed (>=3 items); vision DRAW-SEED-002..004 "
        "surfaced as vision_based; flags default OFF."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
