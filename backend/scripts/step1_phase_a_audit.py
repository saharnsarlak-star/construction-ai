"""Step 1 Phase A audit — read-only DB + storage state (writes JSON report)."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, text

from app.database import SessionLocal, init_db
from app.models import CatalogStandardAsset
from app.standards_engine.models import Requirement, StandardClause


async def main() -> None:
    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "errors": []}
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"init_db: {exc}")

    async with SessionLocal() as session:
        # Detect backend
        try:
            dialect = (await session.execute(text("SELECT 1"))).scalar()
            report["db_connected"] = dialect == 1
        except Exception as exc:  # noqa: BLE001
            report["db_connected"] = False
            report["errors"].append(f"db ping: {exc}")
            _write(report)
            return

        assets = (await session.execute(select(CatalogStandardAsset))).scalars().all()
        report["catalog_assets"] = []
        for a in assets:
            cc = (
                await session.execute(
                    select(func.count(StandardClause.id)).where(StandardClause.standard_id == a.id)
                )
            ).scalar()
            rc = (
                await session.execute(
                    select(func.count(Requirement.id))
                    .join(StandardClause, Requirement.clause_id == StandardClause.id)
                    .where(StandardClause.standard_id == a.id)
                )
            ).scalar()
            clauses = (
                await session.execute(
                    select(StandardClause).where(StandardClause.standard_id == a.id)
                )
            ).scalars().all()
            with_page = sum(1 for c in clauses if c.source_page is not None)
            local_exists = False
            sp = a.stored_path or ""
            if sp and not sp.startswith("http"):
                for base in (
                    Path(__file__).resolve().parent.parent / "storage",
                    Path(__file__).resolve().parent.parent,
                ):
                    if (base / sp).exists():
                        local_exists = True
                        break
            report["catalog_assets"].append(
                {
                    "id": a.id,
                    "standard_code": a.standard_code,
                    "stored_path": sp,
                    "original_name": a.original_name,
                    "country_code": a.country_code,
                    "standard_version": a.standard_version,
                    "effective_date": str(a.effective_date) if a.effective_date else None,
                    "extracted_text_len": len(a.extracted_text or ""),
                    "extraction_status": a.extraction_status,
                    "size_bytes": a.size_bytes,
                    "clause_count": int(cc or 0),
                    "requirement_count": int(rc or 0),
                    "clauses_with_source_page": with_page,
                    "local_file_exists": local_exists,
                }
            )

        # Unique index check (Postgres only)
        try:
            idx = (
                await session.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE indexname = 'uq_standard_clauses_standard_clause'"
                    )
                )
            ).scalar_one_or_none()
            report["unique_clause_index"] = idx is not None
        except Exception:
            report["unique_clause_index"] = None

    _write(report)


def _write(report: dict) -> None:
    out = Path(__file__).resolve().parent.parent / "step1_phase_a_audit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
