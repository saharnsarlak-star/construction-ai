"""Create catalog/auth tables if missing, then smoke-test admin catalog upload."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.database import engine, init_db
from app.main import app
from fastapi.testclient import TestClient


async def _check() -> None:
    await init_db()
    async with engine.begin() as conn:
        r = await conn.execute(
            text(
                "SELECT to_regclass('public.catalog_standard_assets') AS csa, "
                "to_regclass('public.app_users') AS users"
            )
        )
        print("tables:", dict(r.mappings().one()))


def main() -> None:
    asyncio.run(_check())
    client = TestClient(app)
    me = client.get("/api/auth/me", headers={"X-API-Token": "dev-admin-token"})
    print("me:", me.status_code, me.text[:160])
    up = client.post(
        "/api/standards/catalog",
        headers={"X-API-Token": "dev-admin-token"},
        data={"standard_code": "TEST-01", "title": "Test Std"},
        files={"file": ("t.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    print("upload:", up.status_code, up.text[:400])


if __name__ == "__main__":
    main()
