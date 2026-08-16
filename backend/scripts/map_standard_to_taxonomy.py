"""Map a standard document (Code55 DOCX) to IR tender taxonomy codes.

Usage (from backend/):
  python scripts/map_standard_to_taxonomy.py "C:/path/Code55-011.docx"
  python scripts/map_standard_to_taxonomy.py "C:/path/Code55-011.docx" --section 2-2
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", help="Path to standard .docx file")
    parser.add_argument("--section", default=None, help="Optional clause prefix e.g. 2-2")
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default: backend/code55_taxonomy_map.json)",
    )
    args = parser.parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"File not found: {docx_path}")
        return 1

    from app.services.extractor import extract_document_full
    from app.standards_engine.ingestion.clause_parser import parse_standards_text
    from app.tender_taxonomy import warm_taxonomy_cache
    from app.tender_taxonomy.standard_mapper import map_clauses_to_taxonomy, summarize_mappings

    from app.tender_taxonomy.standard_codes import CODE55_FAMILY

    warm_taxonomy_cache()

    print(f"Extracting: {docx_path.name} ({docx_path.stat().st_size // 1024} KB)...")
    extracted = extract_document_full(docx_path, allow_ocr=False)
    text = (extracted.merged_text or "").strip()
    print(f"Text length: {len(text):,} chars")

    clauses = parse_standards_text(text, mode="auto", section_prefix=args.section)
    print(f"Parsed clauses: {len(clauses)}")

    mapped = map_clauses_to_taxonomy(clauses, family_code=CODE55_FAMILY)
    summary = summarize_mappings(mapped)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(docx_path),
        "text_chars": len(text),
        "section_prefix": args.section,
        "summary": summary,
        "mappings": mapped,
    }

    out_path = Path(args.out) if args.out else ROOT / "code55_taxonomy_map.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        if k != "top_taxonomy_codes":
            print(f"  {k}: {v}")
    print("  top_taxonomy_codes:")
    for row in summary["top_taxonomy_codes"][:10]:
        print(f"    {row['code']}: {row['count']} clauses")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
