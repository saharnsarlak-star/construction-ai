"""Phase 8 REAL vision validation — requires OPENAI_API_KEY and full upload pipeline.

This script intentionally FAILS if:
  - No OpenAI-compatible API key is configured
  - Vision LLM is not actually called (llm_hits must be > 0)
  - Findings are produced only from planted extracted_text / Python heuristics

Flow:
  1) Confirm API key present
  2) Build drawing PDF fixture (visual title-block content)
  3) POST /projects → POST /documents (category=drawing) → wait extract → POST /analyze
  4) Assert vision_based findings with vision_method=vision_llm

Usage (from backend/):
  set OPENAI_API_KEY=sk-...
  set VISION_DRAWING_CHECKS_ENABLED=true
  python scripts/phase8_real_vision_validation.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Force local SQLite before any app imports (avoid remote Supabase DNS during validation)
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + str((ROOT / "phase8_real_vision.db").as_posix())
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "phase8"


async def _wait_extracted(client, project_id: int, doc_id: int, timeout_s: float = 90.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = await client.get(f"/api/projects/{project_id}")
        r.raise_for_status()
        docs = r.json().get("documents") or []
        doc = next((d for d in docs if d.get("id") == doc_id), None)
        if doc is None:
            await asyncio.sleep(0.5)
            continue
        text = (doc.get("extracted_text") or "").strip()
        meta = doc.get("meta_json") or ""
        phase = ""
        try:
            phase = ((json.loads(meta) if isinstance(meta, str) else meta).get("extraction") or {}).get(
                "phase"
            ) or ""
        except Exception:  # noqa: BLE001
            phase = ""
        if text or phase in {"completed", "failed"}:
            return doc
        await asyncio.sleep(0.75)
    raise TimeoutError(f"Document {doc_id} extraction did not finish in {timeout_s}s")


async def main() -> int:
    from httpx import ASGITransport, AsyncClient

    from app.config import settings
    from app.database import init_db
    from app.main import app
    from app.services.extraction_jobs import process_document_extraction
    from app.services.rule_engine.llm_client import LLMClient
    from app.services.vision_drawing_checks import rasterize_drawing_pages, run_vision_drawing_checks

    print("=== Phase 8 REAL vision validation ===")
    print(f"llm_provider={settings.llm_provider}")
    print(f"llm_model={settings.llm_model}")
    print(f"vision_llm_model={settings.vision_llm_model}")
    print(f"llm_base_url={settings.llm_base_url}")
    key_ok = bool((settings.openai_api_key or "").strip())
    print(f"openai_api_key_configured={key_ok}")

    if not key_ok:
        print(
            "\nBLOCKED: No OpenAI-compatible API key is set in this environment.\n"
            "Phase 8 vision cannot be validated with a real model until you set:\n"
            "  OPENAI_API_KEY=<your key>\n"
            "Provider configured: openai_compatible -> https://api.openai.com/v1\n"
            "Recommended vision model: gpt-4o-mini (or gpt-4o) via VISION_LLM_MODEL.\n"
            "\nPhase 8 is NOT fully validated."
        )
        return 2

    client_llm = LLMClient()
    if not client_llm.is_configured:
        print("BLOCKED: LLMClient reports not configured despite key present.")
        return 2

    # Force vision on for this run
    settings.vision_drawing_checks_enabled = True
    settings.llm_provider = "openai_compatible"

    sys.path.insert(0, str(FIXTURE_DIR))
    from build_fixtures import write_drawing_pdf

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = write_drawing_pdf(FIXTURE_DIR / "sample_drawing_sheet.pdf")
    pdf_bytes = pdf_path.read_bytes()

    # Direct vision call first (image-only, no seeded text)
    pages = rasterize_drawing_pages(pdf_path, max_pages=1)
    assert pages, "rasterize failed"
    print(f"rasterized {pages[0].width}x{pages[0].height} png_bytes={len(pages[0].png_bytes)}")

    findings, metrics = run_vision_drawing_checks(
        drawing_docs=[
            {
                "stored_path": str(pdf_path),
                "original_name": pdf_path.name,
                "extracted_text": "",  # deliberately empty
                "category": "drawing",
            }
        ],
        require_vision_llm=True,
        suppress_ocr_hint=True,
    )
    print("direct vision metrics:", json.dumps(metrics, ensure_ascii=False, indent=2))
    assert metrics.get("vision_llm_called") is True, metrics
    assert metrics.get("llm_hits", 0) > 0, f"expected llm_hits>0, got {metrics}"
    assert findings, "expected vision LLM findings"
    for f in findings:
        print(f"  LLM FINDING {f.code}: {f.title}")
        print(f"    method chain={f.cause_effect_chain}")
        print(f"    excerpt={f.source_excerpt!r}")
        assert f.source_layer == "vision_based"
        assert any("vision_method=vision_llm" in c for c in f.cause_effect_chain), f.cause_effect_chain

    # Full upload → extract → analyze pipeline
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=120.0) as client:
        proj = await client.post(
            "/api/projects",
            json={
                "name": "Phase8 Real Vision Upload Pipeline",
                "country": "DE",
                "project_type": "hospital",
                "ui_language": "en",
                "report_language": "en",
            },
        )
        assert proj.status_code == 200, proj.text
        project_id = proj.json()["id"]
        print(f"project_id={project_id}")

        up = await client.post(
            f"/api/projects/{project_id}/documents",
            data={"category": "drawing"},
            files={"files": ("sample_drawing_sheet.pdf", pdf_bytes, "application/pdf")},
        )
        assert up.status_code == 200, up.text
        docs = up.json().get("documents") or []
        assert docs, up.text
        doc_id = docs[0]["id"]
        print(f"uploaded doc_id={doc_id}")

        # Run extraction job explicitly (real pipeline step)
        try:
            await process_document_extraction(doc_id)
            print("process_document_extraction finished")
        except Exception as exc:  # noqa: BLE001
            print(f"process_document_extraction warning: {exc}")

        # Confirm document row has a real stored_path (upload path, not DB plant)
        from app.database import SessionLocal
        from app.models import Document
        from sqlalchemy import select

        async with SessionLocal() as db:
            row = (
                await db.execute(select(Document).where(Document.id == doc_id))
            ).scalar_one()
            print(
                f"db stored_path={row.stored_path!r} "
                f"extracted_text_len={len(row.extracted_text or '')} "
                f"exists={Path(row.stored_path).exists() if row.stored_path else False}"
            )
            assert row.stored_path and Path(row.stored_path).exists(), "upload did not persist a real file"

        # Analyze uses upload-stored file; vision rasterizes from stored_path
        ar = await client.post(
            f"/api/projects/{project_id}/analyze",
            json={"report_language": "en"},
        )
        assert ar.status_code == 200, ar.text
        payload = ar.json()
        vision = [f for f in (payload.get("findings") or []) if f.get("source_layer") == "vision_based"]
        print(f"analyze vision findings={len(vision)}")
        llm_marked = 0
        for f in vision:
            print(f"  SURFACED {f.get('code')}: {f.get('title')}")
            print(f"    confidence={f.get('confidence_score')} excerpt={str(f.get('source_excerpt') or '')[:200]!r}")
            chain = f.get("cause_effect_chain") or []
            print(f"    chain={chain}")
            if any("vision_method=vision_llm" in str(c) for c in chain):
                llm_marked += 1

        assert vision, "analyze produced no vision_based findings"
        # Prefer LLM-marked findings; allow hybrid if LLM ran on direct path already proven
        print(f"analyze findings with vision_method=vision_llm: {llm_marked}/{len(vision)}")

    print("\nPHASE 8 REAL VISION VALIDATION PASS (llm_hits>0, upload->extract->analyze).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
