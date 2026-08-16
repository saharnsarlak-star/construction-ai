"""Generate Standards Library QA report (Phase A acceptance)."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, init_db
from app.models import CatalogStandardAsset
from app.standards_engine.models import Requirement, RequirementType, StandardClause


async def _build_report(standard_code: str) -> dict:
    async with SessionLocal() as session:
        asset = (
            await session.execute(
                select(CatalogStandardAsset).where(
                    CatalogStandardAsset.standard_code == standard_code
                )
            )
        ).scalar_one_or_none()

        if asset is None:
            return {"error": f"Standard {standard_code} not found in catalog"}

        clauses = (
            await session.execute(
                select(StandardClause).where(StandardClause.standard_id == asset.id)
            )
        ).scalars().all()

        req_count = (
            await session.execute(
                select(func.count(Requirement.id))
                .join(StandardClause, Requirement.clause_id == StandardClause.id)
                .where(StandardClause.standard_id == asset.id)
            )
        ).scalar_one()

        clauses_with_page = sum(1 for c in clauses if c.source_page is not None)
        clauses_without_reqs: list[str] = []
        modality_issues: list[dict] = []

        for clause in clauses:
            reqs = (
                await session.execute(
                    select(Requirement).where(Requirement.clause_id == clause.id)
                )
            ).scalars().all()
            if not reqs:
                clauses_without_reqs.append(clause.clause_number)
            for r in reqs:
                text = r.requirement_text or ""
                if "باید" in text and r.requirement_type == RequirementType.RECOMMENDATION:
                    modality_issues.append(
                        {
                            "clause": clause.clause_number,
                            "requirement_id": r.id,
                            "issue": "باید marked as recommendation",
                        }
                    )

        page_pct = (
            round(100.0 * clauses_with_page / len(clauses), 1) if clauses else 0.0
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "standard_code": standard_code,
            "catalog": {
                "id": asset.id,
                "country_code": asset.country_code,
                "standard_version": asset.standard_version,
                "effective_date": str(asset.effective_date) if asset.effective_date else None,
                "extracted_text_len": len(asset.extracted_text or ""),
                "extraction_status": asset.extraction_status,
            },
            "counts": {
                "clauses": len(clauses),
                "requirements": int(req_count or 0),
                "clauses_with_source_page": clauses_with_page,
                "source_page_coverage_pct": page_pct,
            },
            "quality": {
                "clauses_without_requirements": clauses_without_reqs,
                "modality_issues": modality_issues,
            },
            "acceptance": {
                "min_clauses_met": len(clauses) >= 5,
                "source_page_target_met": page_pct >= 90.0 if clauses else False,
                "catalog_metadata_present": bool(asset.country_code),
            },
        }


def _to_markdown(report: dict) -> str:
    if report.get("error"):
        return f"# Standards QA Report\n\nError: {report['error']}\n"

    lines = [
        "# Standards QA Report",
        "",
        f"**Standard:** {report['standard_code']}",
        f"**Generated:** {report['generated_at']}",
        "",
        "## Catalog",
        "",
        f"- Country: {report['catalog']['country_code']}",
        f"- Version: {report['catalog']['standard_version']}",
        f"- Extracted text length: {report['catalog']['extracted_text_len']}",
        "",
        "## Counts",
        "",
        f"- Clauses: {report['counts']['clauses']}",
        f"- Requirements: {report['counts']['requirements']}",
        f"- Source page coverage: {report['counts']['source_page_coverage_pct']}%",
        "",
        "## Quality issues",
        "",
    ]
    empty = report["quality"]["clauses_without_requirements"]
    if empty:
        lines.append(f"- Clauses without requirements: {', '.join(empty)}")
    else:
        lines.append("- No empty-clause issues")
    mod = report["quality"]["modality_issues"]
    if mod:
        lines.append(f"- Modality issues: {len(mod)}")
    else:
        lines.append("- No modality issues detected")

    lines.extend(
        [
            "",
            "## Acceptance checks",
            "",
            f"- Min clauses (≥5): {'PASS' if report['acceptance']['min_clauses_met'] else 'FAIL'}",
            f"- Source page ≥90%: {'PASS' if report['acceptance']['source_page_target_met'] else 'FAIL'}",
            f"- Catalog metadata: {'PASS' if report['acceptance']['catalog_metadata_present'] else 'FAIL'}",
        ]
    )
    return "\n".join(lines) + "\n"


async def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else "CODE55-VOL1-IR"
    await init_db()
    report = await _build_report(code)

    out_dir = Path(__file__).resolve().parent.parent
    json_path = out_dir / "standards_qa_report.json"
    md_path = out_dir / "standards_qa_report.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_to_markdown(report), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
