"""Step 1 — Phase A verification orchestrator (writes step1_phase_a_report.json)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.database import SessionLocal, init_db
from app.models import CatalogStandardAsset
from app.standards_engine.ingestion.pdf_extract import extract_catalog_standard_pages
from app.standards_engine.models import Requirement, StandardClause


BACKEND = Path(__file__).resolve().parent.parent
SAMPLE = BACKEND / "app/standards_engine/ingestion/samples/sample_clause_2-2-3.txt"


async def _db_snapshot(standard_code: str) -> dict:
    async with SessionLocal() as session:
        asset = (
            await session.execute(
                select(CatalogStandardAsset).where(CatalogStandardAsset.standard_code == standard_code)
            )
        ).scalar_one_or_none()
        if asset is None:
            return {"error": f"{standard_code} not in catalog"}
        clauses = (
            await session.execute(
                select(StandardClause).where(StandardClause.standard_id == asset.id)
            )
        ).scalars().all()
        reqs = (
            await session.execute(
                select(Requirement, StandardClause.clause_number, StandardClause.source_page)
                .join(StandardClause, Requirement.clause_id == StandardClause.id)
                .where(StandardClause.standard_id == asset.id)
            )
        ).all()
        modality_issues = []
        for r, cnum, _sp in reqs:
            if "باید" in (r.requirement_text or "") and r.requirement_type.value == "recommendation":
                modality_issues.append({"clause": cnum, "requirement_id": r.id})
        with_page = sum(1 for c in clauses if c.source_page is not None)
        pdf_ok = False
        pdf_pages = 0
        if asset.stored_path and str(asset.stored_path).lower().endswith(".pdf"):
            try:
                from app.services import storage as file_storage

                p = await file_storage.open_for_read(asset.stored_path)
                ex = extract_catalog_standard_pages(Path(p))
                pdf_ok = ex.page_count > 0 and len(ex.merged_text) > 100
                pdf_pages = ex.page_count
            except Exception as exc:  # noqa: BLE001
                pdf_ok = False
                pdf_pages = 0
        return {
            "catalog": {
                "id": asset.id,
                "standard_code": asset.standard_code,
                "stored_path": asset.stored_path,
                "country_code": asset.country_code,
                "standard_version": asset.standard_version,
                "effective_date": str(asset.effective_date) if asset.effective_date else None,
                "publisher": asset.publisher,
                "extracted_text_len": len(asset.extracted_text or ""),
                "extraction_status": asset.extraction_status,
                "size_bytes": asset.size_bytes,
            },
            "counts": {
                "clauses": len(clauses),
                "requirements": len(reqs),
                "clauses_with_source_page": with_page,
                "source_page_pct": round(100 * with_page / len(clauses), 1) if clauses else 0,
            },
            "quality": {
                "modality_issues": modality_issues,
                "clauses_without_requirements": [
                    c.clause_number
                    for c in clauses
                    if not any(cn == c.clause_number for _, cn, _ in reqs)
                ],
            },
            "pdf_pipeline": {
                "real_pdf_available": str(asset.stored_path).lower().endswith(".pdf") and asset.size_bytes > 1000,
                "pdf_extract_ok": pdf_ok,
                "pdf_page_count": pdf_pages,
            },
        }


async def main() -> None:
    report: dict = {
        "step": 1,
        "phase": "A",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "automated_tests": {},
        "ingest": {},
        "db_after": {},
        "acceptance": {},
    }

    # 1) Unit tests
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_standards_phase_a.py", "-v"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    report["automated_tests"] = {
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout_tail": proc.stdout.splitlines()[-15:],
        "stderr_tail": proc.stderr.splitlines()[-10:],
    }

    await init_db()

    # 2) Re-ingest sample with force (LLM + DB)
    ingest_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.standards_engine.ingestion.pipeline",
            "--save",
            "--force",
            "--text",
            str(SAMPLE),
        ],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    report["ingest"] = {
        "exit_code": ingest_proc.returncode,
        "ok": ingest_proc.returncode == 0,
        "stdout_tail": ingest_proc.stdout.splitlines()[-20:],
        "stderr_tail": ingest_proc.stderr.splitlines()[-10:],
    }

    # 3) Duplicate skip check
    dup_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.standards_engine.ingestion.pipeline",
            "--save",
            "--text",
            str(SAMPLE),
        ],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    report["duplicate_skip"] = {
        "exit_code": dup_proc.returncode,
        "skipped_all": "skipped 5" in dup_proc.stdout or "Skip existing clause" in dup_proc.stdout,
        "stdout_tail": dup_proc.stdout.splitlines()[-10:],
    }

    # 4) DB snapshot + QA script
    report["db_after"] = await _db_snapshot("CODE55-VOL1-IR")

    qa_proc = subprocess.run(
        [sys.executable, "scripts/standards_qa_report.py", "CODE55-VOL1-IR"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    qa_path = BACKEND / "standards_qa_report.json"
    report["qa_report"] = {
        "exit_code": qa_proc.returncode,
        "file_exists": qa_path.exists(),
        "content": json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.exists() else None,
    }

    db = report["db_after"]
    real_pdf = db.get("pdf_pipeline", {}).get("real_pdf_available", False)
    report["acceptance"] = {
        "unit_tests": report["automated_tests"]["passed"],
        "sample_ingest_llm": report["ingest"]["ok"],
        "duplicate_prevention": report["duplicate_skip"].get("skipped_all", False),
        "min_clauses_sample": (db.get("counts", {}).get("clauses") or 0) >= 5,
        "catalog_metadata": bool(db.get("catalog", {}).get("country_code")),
        "real_pdf_ingested": real_pdf,
        "real_pdf_clause_count_20plus": (db.get("counts", {}).get("clauses") or 0) >= 20 if real_pdf else None,
        "source_page_90pct": (db.get("counts", {}).get("source_page_pct") or 0) >= 90 if real_pdf else None,
        "step1_fully_accepted": False,
    }
    report["acceptance"]["step1_fully_accepted"] = (
        report["acceptance"]["unit_tests"]
        and report["acceptance"]["sample_ingest_llm"]
        and report["acceptance"]["duplicate_prevention"]
        and report["acceptance"]["min_clauses_sample"]
        and report["acceptance"]["catalog_metadata"]
        and report["acceptance"]["real_pdf_ingested"]
        and (report["acceptance"]["real_pdf_clause_count_20plus"] is True)
        and (report["acceptance"]["source_page_90pct"] is True)
    )

    out = BACKEND / "step1_phase_a_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["acceptance"], ensure_ascii=False, indent=2))
    print(f"Full report: {out}")


if __name__ == "__main__":
    asyncio.run(main())
