"""Phase 0 smoke test: Admin uploads catalog PDF, User downloads it.

Run from backend/:
  python scripts/phase0_standards_auth_test.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Minimal valid-ish PDF
MINI_PDF = b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R >>endobj
4 0 obj<< /Length 44 >>stream
BT /F1 12 Tf 40 100 Td (Phase0 Test) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000214 00000 n 
trailer<< /Size 5 /Root 1 0 R >>
startxref
307
%%EOF
"""


async def main() -> int:
    from httpx import ASGITransport, AsyncClient

    from app.config import settings
    from app.database import init_db
    from app.main import app

    await init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1) Auth roles
        anon = await client.get("/api/auth/me")
        assert anon.status_code == 401, anon.text
        print("PASS anon -> 401")

        admin_login = await client.post(
            "/api/auth/login",
            json={"email": settings.admin_email, "password": settings.admin_password},
        )
        assert admin_login.status_code == 200, admin_login.text
        admin_token = admin_login.json()["api_token"]
        assert admin_login.json()["is_admin"] is True
        print("PASS admin login", admin_login.json())

        admin_me = await client.get("/api/auth/me", headers={"X-API-Token": admin_token})
        assert admin_me.status_code == 200
        assert admin_me.json()["is_admin"] is True
        print("PASS admin me", admin_me.json())

        user_login = await client.post(
            "/api/auth/login",
            json={"email": settings.user_email, "password": settings.user_password},
        )
        assert user_login.status_code == 200, user_login.text
        user_token = user_login.json()["api_token"]
        assert user_login.json()["is_admin"] is False
        print("PASS user login", user_login.json())

        user_me = await client.get("/api/auth/me", headers={"X-API-Token": user_token})
        assert user_me.status_code == 200
        assert user_me.json()["is_admin"] is False
        print("PASS user me", user_me.json())

        # 2) Create project
        proj = await client.post(
            "/api/projects",
            json={
                "name": "Phase0 Standards Auth",
                "country": "IR",
                "project_type": "office",
                "ui_language": "en",
                "report_language": "en",
            },
        )
        assert proj.status_code == 200, proj.text
        project_id = proj.json()["id"]
        print("PASS project", project_id)

        # 3) User cannot upload catalog
        denied = await client.post(
            "/api/standards/catalog",
            headers={"X-API-Token": user_token},
            data={
                "standard_code": "PHASE0_TEST_STD",
                "title": "Phase0 Test Standard",
                "standard_class": "technical",
                "project_id": str(project_id),
            },
            files={"file": ("phase0_test.pdf", MINI_PDF, "application/pdf")},
        )
        assert denied.status_code == 403, denied.text
        print("PASS user catalog upload forbidden", denied.status_code)

        # 4) User cannot upload project category=standard
        denied_doc = await client.post(
            f"/api/projects/{project_id}/documents",
            headers={"X-API-Token": user_token},
            data={"category": "standard"},
            files={"files": ("phase0_test.pdf", MINI_PDF, "application/pdf")},
        )
        assert denied_doc.status_code == 403, denied_doc.text
        print("PASS user project-standard upload forbidden", denied_doc.status_code)

        # 5) Admin uploads catalog PDF
        up = await client.post(
            "/api/standards/catalog",
            headers={"X-API-Token": admin_token},
            data={
                "standard_code": "PHASE0_TEST_STD",
                "title": "Phase0 Test Standard",
                "standard_class": "technical",
                "publisher": "Phase0",
                "project_id": str(project_id),
            },
            files={"file": ("phase0_test.pdf", MINI_PDF, "application/pdf")},
        )
        assert up.status_code == 200, up.text
        body = up.json()
        assert body["standard_code"] == "PHASE0_TEST_STD"
        assert body["has_pdf"] is True
        assert body["size_bytes"] == len(MINI_PDF)
        print("PASS admin catalog upload", body)

        # 6) Checklist shows has_pdf
        standards = await client.get(f"/api/projects/{project_id}/standards")
        assert standards.status_code == 200, standards.text
        rows = standards.json()
        hit = next((r for r in rows if r["standard_code"] == "PHASE0_TEST_STD"), None)
        assert hit is not None, "uploaded standard missing from checklist"
        assert hit["has_pdf"] is True
        print("PASS checklist has_pdf", hit["standard_code"], hit["is_selected"])

        # 7) User downloads original PDF
        dl = await client.get(
            f"/api/projects/{project_id}/standards/PHASE0_TEST_STD/download",
            headers={"X-API-Token": user_token},
        )
        assert dl.status_code == 200, dl.text
        assert dl.content.startswith(b"%PDF"), dl.content[:20]
        assert len(dl.content) == len(MINI_PDF)
        print("PASS user download bytes", len(dl.content), "content-type", dl.headers.get("content-type"))

        # 8) Download for code without PDF -> 404
        no_pdf = await client.get(
            f"/api/projects/{project_id}/standards/IR_NBR_01/download",
            headers={"X-API-Token": user_token},
        )
        # May be 403 if not on list, or 404 if on list without asset
        assert no_pdf.status_code in {403, 404}, no_pdf.text
        print("PASS no-pdf download status", no_pdf.status_code)

    print("\nALL PHASE0 TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
