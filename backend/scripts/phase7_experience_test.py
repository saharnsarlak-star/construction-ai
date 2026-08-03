"""Phase 7 — Experience Knowledge layer: admin CREATE + analysis surfacing.

1. Creates 1–2 ExperienceKnowledgeItem rows via POST /api/experience (Admin)
2. Creates a hospital project and runs analyze with EXPERIENCE_LAYER_ENABLED
3. Confirms experience findings appear with finding_category=experience,
   source_layer=experience_based, and mandatory_rule=false

Usage (from backend/):
  set EXPERIENCE_LAYER_ENABLED=true   # or toggled in-script
  python scripts/phase7_experience_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def _run() -> int:
    from fastapi.testclient import TestClient

    from app.config import Settings, settings
    from app.database import SessionLocal, init_db
    from app.main import app
    from app.models import CountryCode, DocumentCategory, LanguageCode, Project, ProjectType
    from app.services.experience_layer import match_experience_findings

    print("=== Phase 7 Experience Knowledge test ===")
    code_defaults = Settings(_env_file=None)
    print(f"code default experience_layer_enabled={code_defaults.experience_layer_enabled}")
    assert code_defaults.experience_layer_enabled is False

    await init_db()

    # Enable only for this test run
    settings.experience_layer_enabled = True
    print(f"test run experience_layer_enabled={settings.experience_layer_enabled}")

    client = TestClient(app)
    admin = {"X-API-Token": settings.admin_api_token}
    user = {"X-API-Token": settings.user_api_token}
    suffix = __import__("uuid").uuid4().hex[:6].upper()

    # Non-admin cannot create
    denied = client.post(
        "/api/experience",
        headers=user,
        json={"title": "Should fail", "description": "x", "related_project_type": "hospital"},
    )
    print(f"POST /api/experience as user → {denied.status_code} (expect 403)")
    assert denied.status_code == 403

    # Admin creates hospital MEP experience
    r1 = client.post(
        "/api/experience",
        headers=admin,
        json={
            "experience_id": f"EXP-HOSP-MEP-DELAY-{suffix}",
            "title": "Hospital projects often have MEP delays",
            "description": (
                "On prior hospital tenders, MEP coordination gaps between drawings, "
                "specs, and BOQ repeatedly delayed award and caused post-award claims."
            ),
            "category": "delay",
            "origin_kind": "admin_curated",
            "related_project_type": "hospital",
            "related_risk_id": "RISK-SCHED-RESOURCE-001",
            "confidence_level": "high",
            "validation_status": "validated",
            "recommended_prevention": (
                "Require a coordinated MEP interface matrix and lead-time schedule "
                "before tender close. Advisory experience — not a mandatory code rule."
            ),
        },
    )
    print(f"POST experience #1 → {r1.status_code}")
    assert r1.status_code == 201, r1.text
    exp1 = r1.json()
    print(f"  created: {exp1['experience_id']} origin={exp1['origin_kind']} types={exp1['related_project_types']}")

    r2 = client.post(
        "/api/experience",
        headers=admin,
        json={
            "experience_id": f"EXP-HOSP-FIRE-SPEC-{suffix}",
            "title": "Hospital fire compartment specs often underspecified",
            "description": (
                "Previous hospital projects saw claim patterns where fire rating and "
                "compartment walls were vague in Employer Requirements."
            ),
            "category": "compliance",
            "origin_kind": "admin_curated",
            "related_project_types": ["hospital"],
            "confidence_level": "medium",
            "validation_status": "validated",
            "recommended_prevention": "Bind explicit REI ratings to wall type marks in ER/specs.",
        },
    )
    print(f"POST experience #2 → {r2.status_code}")
    assert r2.status_code == 201, r2.text

    listed = client.get("/api/experience", headers=admin)
    print(f"GET /api/experience → {listed.status_code} count={len(listed.json())}")
    assert listed.status_code == 200
    assert len(listed.json()) >= 2

    # Create hospital project + minimal tender doc, then analyze
    async with SessionLocal() as db:
        project = Project(
            name="Phase7 Hospital Experience Test",
            country=CountryCode.DE,
            project_type=ProjectType.HOSPITAL,
            ui_language=LanguageCode.EN,
            report_language=LanguageCode.EN,
            description="Hospital tender for experience-layer surfacing",
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        project_id = project.id

        text = (
            "HOSPITAL TENDER\nEmployer Requirements\n"
            "MEP systems shall be coordinated. Fire compartment walls as required.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write(text)
            tmp_path = Path(tf.name)

        from app.models import Document

        doc = Document(
            project_id=project_id,
            category=DocumentCategory.TENDER,
            original_name="hospital_er.txt",
            stored_path=str(tmp_path),
            content_type="text/plain",
            size_bytes=tmp_path.stat().st_size,
            extracted_text=text,
            meta_json=json.dumps(
                {"extraction": {"method": "text", "confidenceScore": 95}, "status": "ready"},
                ensure_ascii=False,
            ),
        )
        db.add(doc)
        await db.commit()

        # Direct service match (unit-level)
        matched = await match_experience_findings(
            db, project_type=ProjectType.HOSPITAL, existing_findings=[], lang=LanguageCode.EN
        )
        print(f"\nmatch_experience_findings(hospital) → {len(matched)}")
        for m in matched:
            print(f"  {m.code} | cat={m.finding_category} | layer={m.source_layer}")
            print(f"    title={m.title}")
            assert m.finding_category == "experience"
            assert m.source_layer == "experience_based"
            assert "not a mandatory rule" in m.description.lower() or "EXPERIENCE-BASED" in m.description
            assert "mandatory_rule=false" in m.cause_effect_chain
        assert len(matched) >= 2, "expected both hospital experience items to match"

        # Infrastructure project should NOT match hospital-only items
        infra = await match_experience_findings(
            db, project_type=ProjectType.INFRASTRUCTURE, existing_findings=[], lang=LanguageCode.EN
        )
        hospital_codes = {m.code for m in matched}
        leaked = [f for f in infra if f.code in hospital_codes]
        print(f"match on infrastructure (should not include hospital items): leaked={len(leaked)}")
        assert not leaked

    # Full analyze via API
    ar = client.post(
        f"/api/projects/{project_id}/analyze",
        headers=admin,
        json={"report_language": "en"},
    )
    print(f"\nPOST /api/projects/{project_id}/analyze → {ar.status_code}")
    assert ar.status_code == 200, ar.text
    payload = ar.json()
    findings = payload.get("findings") or []
    exp_findings = [
        f
        for f in findings
        if f.get("finding_category") == "experience" or f.get("source_layer") == "experience_based"
    ]
    print(f"analysis findings total={len(findings)} experience={len(exp_findings)}")
    for f in exp_findings:
        print(f"  SURFACED: {f.get('code')}")
        print(f"    title={f.get('title')}")
        print(f"    finding_category={f.get('finding_category')} source_layer={f.get('source_layer')}")
        print(f"    confidence_score={f.get('confidence_score')}")
        desc = f.get("description") or ""
        assert "EXPERIENCE-BASED" in desc or "experience" in (f.get("title") or "").lower()
        assert f.get("finding_category") == "experience"
        assert f.get("source_layer") == "experience_based"
        chain = f.get("cause_effect_chain") or []
        assert any("mandatory_rule=false" in str(c) for c in chain) or any(
            "advisory=true" in str(c) for c in chain
        )

    assert len(exp_findings) >= 2, f"expected both experience findings in analysis, got {len(exp_findings)}"
    titles = " ".join(f.get("title") or "" for f in exp_findings)
    assert "MEP delays" in titles
    assert "fire compartment" in titles.lower() or "Fire" in titles

    # Flag OFF → no match
    settings.experience_layer_enabled = False
    async with SessionLocal() as db:
        off = await match_experience_findings(db, project_type=ProjectType.HOSPITAL)
        print(f"\nFlag OFF match count={len(off)} (expect 0)")
        assert off == []

    print(
        "\nPHASE 7 PASS: Admin API created experience items; "
        "hospital analysis surfaces experience-based (non-mandatory) findings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
