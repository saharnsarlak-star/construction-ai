"""Step 1 post-fix verification on real Standard 55 Word doc (no DB required)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.extractor import extract_document_full
from app.standards_engine.ingestion.catalog_metadata import parse_catalog_file_metadata
from app.standards_engine.ingestion.clause_parser import (
    filter_substantive_clauses,
    parse_standards_text,
)

DOCX = Path(__file__).resolve().parents[1] / "step1_real_doc" / "Code55-01-www.technobetar.ir_8d77cf14b76f.docx"
OUT = Path(__file__).resolve().parents[1] / "step1_post_fix_report.json"


def main() -> None:
    if not DOCX.exists():
        raise SystemExit(f"Real doc not found: {DOCX}")

    text = (extract_document_full(DOCX, allow_ocr=False).merged_text or "").strip()
    meta = parse_catalog_file_metadata(text)
    all_clauses = parse_standards_text(text)
    substantive = filter_substantive_clauses(all_clauses)
    sec_22 = filter_substantive_clauses(
        parse_standards_text(text, section_prefix="2-2")
    )
    with_page = sum(1 for c in substantive if c.get("source_page"))

    report = {
        "step": 1,
        "phase": "A",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixes_applied": [
            "catalog text cap raised 80k -> 500k with force_refresh",
            "TOC/index stub filtering",
            "virtual source_page for Word (3500 chars/page)",
            "Persian Word metadata parsing",
            "force re-ingest clears old clauses before save",
        ],
        "document": {
            "path": str(DOCX.relative_to(DOCX.parents[1])),
            "extract_chars": len(text),
        },
        "parsing": {
            "clauses_all": len(all_clauses),
            "clauses_substantive": len(substantive),
            "clauses_section_2_2_substantive": len(sec_22),
            "source_page_pct": round(100 * with_page / max(len(substantive), 1), 1),
        },
        "metadata_parsed": meta.as_dict(),
        "acceptance": {
            "min_20_clauses_section_2_2": len(sec_22) >= 20,
            "full_text_not_truncated": len(text) > 300_000,
            "source_page_90pct": with_page / max(len(substantive), 1) >= 0.9,
            "metadata_country": bool(meta.country_code),
            "metadata_version_or_date": bool(meta.standard_version or meta.effective_date),
        },
        "verdict": (
            "ACCEPTED (parse/metadata layer)"
            if len(sec_22) >= 20
            and len(text) > 300_000
            and with_page / max(len(substantive), 1) >= 0.9
            and meta.country_code
            else "NOT ACCEPTED"
        ),
        "db_ingest_note": (
            "Run when Supabase is reachable: "
            "python -m app.standards_engine.ingestion.pipeline "
            "--save-catalog CODE55-VOL1-IR --section 2-2 --force"
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
