"""Quick Supabase DB connectivity check (run from backend folder)."""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

# Allow: python scripts/check_db_connection.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _host_from_database_url(url: str) -> tuple[str, int]:
    normalized = url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(normalized)
    return parsed.hostname or "", parsed.port or 5432


async def _db_ping() -> None:
    from app.database import engine
    from sqlalchemy import text

    async with engine.connect() as conn:
        value = (await conn.execute(text("select 1"))).scalar_one()
        print(f"DB OK (select 1 => {value})")


def main() -> None:
    from app.dns_fallback import install_supabase_dns_fallback, resolve_ipv4

    install_supabase_dns_fallback()
    from app.config import settings

    host, port = _host_from_database_url(settings.database_url)
    print(f"Checking host: {host}:{port}")

    ip = resolve_ipv4(host)
    if ip:
        print(f"DNS OK -> {ip}")
    else:
        print(f"DNS FAILED for {host}")
        print(
            "\nFix tips:\n"
            "  1) Disconnect Tailscale (MagicDNS often breaks Supabase lookups)\n"
            "  2) Set Windows DNS to 8.8.8.8 and 1.1.1.1\n"
            "  3) Run: ipconfig /flushdns\n"
            "  4) Retry this script, then run the ingest command"
        )
        sys.exit(1)

    try:
        asyncio.run(_db_ping())
    except Exception as exc:  # noqa: BLE001
        print(f"DB CONNECT FAILED: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
