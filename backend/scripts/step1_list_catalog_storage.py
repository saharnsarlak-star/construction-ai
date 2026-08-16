"""List Supabase storage objects under catalog_standards/."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings


async def main() -> None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        print(json.dumps({"error": "supabase not configured"}))
        return

    bucket = settings.supabase_bucket
    base = settings.supabase_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
    }
    prefixes = ["catalog_standards", "catalog_standards/CODE55-VOL1-IR", "catalog_standards/CODE55"]
    out: dict = {"bucket": bucket, "lists": {}}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for prefix in prefixes:
            url = f"{base}/storage/v1/object/list/{bucket}"
            try:
                resp = await client.post(url, headers=headers, json={"prefix": prefix, "limit": 100})
                out["lists"][prefix] = {
                    "status": resp.status_code,
                    "objects": resp.json() if resp.status_code == 200 else resp.text[:500],
                }
            except Exception as exc:  # noqa: BLE001
                out["lists"][prefix] = {"error": str(exc)}

    path = Path(__file__).resolve().parent.parent / "step1_storage_list.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    asyncio.run(main())
