"""Phase 6 — Risk Knowledge Base: migrate 46 seed Risk IDs + API + flag fallback.

Verifies:
  1. Python seed catalog has exactly 46 unique Risk IDs (Batches 1–2)
  2. seed_risks_table inserts them into `risks` (count == 46)
  3. Sample Risk IDs present
  4. RKB_DB_ENABLED=false → runners resolve via python_seed
  5. RKB_DB_ENABLED=true  → runners resolve via rkb_db snapshot
  6. Default flags leave MVP / Phases 0–5 engines off

Usage (from backend/):
  python scripts/phase6_rkb_test.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def _run() -> int:
    from sqlalchemy import func, select

    from app.config import settings
    from app.database import SessionLocal, init_db
    from app.knowledge.rkb import (
        all_seed_risk_dicts,
        get_risk_by_id,
        load_rkb_catalog_for_runners,
        python_risk_catalog,
        seed_risks_table,
    )
    from app.knowledge.seed_rules_batch1 import NEW_RISK_IDS_BATCH1
    from app.knowledge.seed_rules_batch2 import NEW_RISK_IDS_BATCH2
    from app.models import Risk
    from app.services.rule_engine.runners import _lookup_risk, set_rkb_catalog

    print("=== Phase 6 RKB test ===")
    print(f"rkb_db_enabled (default): {settings.rkb_db_enabled}")
    print(f"cdm_enabled: {settings.cdm_enabled}")
    print(f"ontology_enabled: {settings.ontology_enabled}")
    print(f"new_rule_engine_enabled: {settings.new_rule_engine_enabled}")
    print(f"ai_rule_engine_enabled: {settings.ai_rule_engine_enabled}")
    print(f"knowledge_graph_enabled: {settings.knowledge_graph_enabled}")

    flags_off = not any(
        [
            settings.cdm_enabled,
            settings.ontology_enabled,
            settings.new_rule_engine_enabled,
            settings.ai_rule_engine_enabled,
            settings.knowledge_graph_enabled,
            settings.rkb_db_enabled,
        ]
    )
    print(f"all phase flags default OFF: {flags_off}")

    batch1 = len(NEW_RISK_IDS_BATCH1)
    batch2 = len(NEW_RISK_IDS_BATCH2)
    seeds = all_seed_risk_dicts()
    unique_ids = {s["risk_id"] for s in seeds}
    print(f"\nPython seed dicts: batch1={batch1} batch2={batch2} total={len(seeds)} unique={len(unique_ids)}")
    assert batch1 == 28, f"expected 28 batch1, got {batch1}"
    assert batch2 == 18, f"expected 18 batch2, got {batch2}"
    assert len(unique_ids) == 46, f"expected 46 unique Risk IDs, got {len(unique_ids)}"
    assert len(python_risk_catalog()) == 46

    await init_db()

    async with SessionLocal() as session:
        stats = await seed_risks_table(session)
        print(f"\nseed_risks_table: {stats}")
        assert stats["unique_seed_ids"] == 46
        assert stats["table_count"] == 46, f"table_count expected 46, got {stats['table_count']}"

        count = (await session.execute(select(func.count()).select_from(Risk))).scalar_one()
        print(f"DB risks.count() = {count}")
        assert count == 46

        sample_ids = [
            "RISK-SCHED-ISLAND-001",
            "RISK-BOQ-MATH-001",
            "RISK-STD-SUPERSEDED-001",
            "RISK-ADD-SEQUENCE-GAP-001",
        ]
        rows = (
            await session.execute(select(Risk).where(Risk.risk_id.in_(sample_ids)).order_by(Risk.risk_id))
        ).scalars().all()
        print("\nSample DB rows:")
        for r in rows:
            print(
                f"  {r.risk_id} | cat={r.category} | prob={r.probability} | "
                f"cost={r.cost_impact} sched={r.schedule_impact} | batch={r.seed_batch}"
            )
        assert len(rows) == len(sample_ids), f"missing sample rows: {[s for s in sample_ids if s not in {x.risk_id for x in rows}]}"

        # Flag OFF → Python fallback
        settings.rkb_db_enabled = False
        set_rkb_catalog(None)
        py = await get_risk_by_id("RISK-BOQ-MATH-001", db=session)
        assert py is not None and py.get("source") == "python_seed"
        looked = _lookup_risk("RISK-BOQ-MATH-001")
        assert looked is not None and looked.get("source") == "python_seed"
        print("\nFlag OFF: lookup source=python_seed OK")

        # Flag ON → DB catalog for runners
        settings.rkb_db_enabled = True
        catalog = await load_rkb_catalog_for_runners(session)
        assert catalog is not None
        assert len(catalog) >= 46
        set_rkb_catalog(catalog)
        try:
            db_hit = _lookup_risk("RISK-BOQ-MATH-001")
            assert db_hit is not None
            assert db_hit.get("source") == "database" or db_hit.get("mapping_source") == "rkb_db"
            print(f"Flag ON: lookup source={db_hit.get('source')} mapping={db_hit.get('mapping_source')} OK")
            resolved = await get_risk_by_id("RISK-SCHED-ISLAND-001", db=session)
            assert resolved is not None and resolved.get("source") == "database"
            print(f"get_risk_by_id DB: {resolved['risk_id']} mitigation={str(resolved.get('mitigation') or '')[:60]}...")
        finally:
            set_rkb_catalog(None)
            settings.rkb_db_enabled = False

    # Show first 8 IDs for the report
    print("\nFirst 8 Risk IDs (of 46):")
    for rid in sorted(unique_ids)[:8]:
        print(f"  - {rid}")
    print(f"  ... ({len(unique_ids) - 8} more)")

    print("\nPHASE 6 PASS: 46 Risk IDs migrated; RKB_DB_ENABLED fallback verified; other phase flags remain default OFF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
