"""DNS/connection warmup for flaky Supabase lookups (e.g. Tailscale MagicDNS)."""

from __future__ import annotations

import asyncio
import socket
from urllib.parse import urlparse

_TRANSIENT_DB_ERRORS = (socket.gaierror, OSError, ConnectionRefusedError)


def db_host_port() -> tuple[str, int]:
    from app.config import settings

    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)
    return parsed.hostname or "", parsed.port or 5432


def is_transient_db_error(exc: BaseException) -> bool:
    if isinstance(exc, _TRANSIENT_DB_ERRORS):
        return True
    for attr in ("__cause__", "__context__", "__orig__"):
        nested = getattr(exc, attr, None)
        if nested and isinstance(nested, _TRANSIENT_DB_ERRORS):
            return True
    text = str(exc).lower()
    return (
        "getaddrinfo failed" in text
        or "11001" in text
        or "connection refused" in text
        or "connection reset" in text
        or "timeout" in text
        or "too many connections" in text
    )


async def run_with_db_retry(
    fn,
    *,
    attempts: int = 4,
    base_delay: float = 1.5,
):
    """Retry coroutine factories on flaky Supabase DNS / pooler connections."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not is_transient_db_error(exc) or attempt >= attempts:
                raise
            delay = min(base_delay * attempt, 8.0)
            await asyncio.sleep(delay)
    if last is not None:
        raise last


async def wait_for_dns(
    host: str,
    port: int,
    *,
    attempts: int = 15,
    base_delay: float = 2.0,
) -> str:
    """Retry DNS until the Supabase pooler host resolves (IPv4). Returns IP."""
    if not host or host in {"localhost", "127.0.0.1"}:
        return host

    from app.dns_fallback import install_supabase_dns_fallback, resolve_ipv4

    install_supabase_dns_fallback()
    ip = resolve_ipv4(host)
    if ip:
        return ip

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port,
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
            ip = infos[0][4][0]
            if attempt > 1:
                print(f"DNS OK for {host} -> {ip} (attempt {attempt}/{attempts})")
            return ip
        except socket.gaierror as exc:
            last = exc
            if attempt >= attempts:
                break
            delay = min(base_delay * attempt, 15)
            print(
                f"DNS lookup failed for {host}, retry in {delay:.0f}s "
                f"(attempt {attempt}/{attempts})..."
            )
            await asyncio.sleep(delay)

    print(dns_fix_hint(host))
    assert last is not None
    raise last


def dns_fix_hint(host: str) -> str:
    return (
        f"\nDNS keeps failing for {host}.\n"
        "Fix (run PowerShell as Administrator):\n"
        "  powershell -ExecutionPolicy Bypass -File scripts/fix_supabase_hosts.ps1\n"
        "Also try: disconnect Tailscale, set DNS to 8.8.8.8, ipconfig /flushdns"
    )


async def ensure_db_reachable(*, dns_attempts: int = 15, connect_attempts: int = 8) -> None:
    """Wait for DNS, then verify Postgres accepts a connection."""
    host, port = db_host_port()
    if host:
        await wait_for_dns(host, port, attempts=dns_attempts)

    from sqlalchemy import text

    from app.database import engine

    last: Exception | None = None
    for attempt in range(1, connect_attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
            if attempt > 1:
                print(f"DB connect OK (attempt {attempt}/{connect_attempts})")
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not is_transient_db_error(exc) or attempt >= connect_attempts:
                raise
            delay = min(2 * attempt, 15)
            print(
                f"DB connect failed ({exc.__class__.__name__}), retry in {delay}s "
                f"(attempt {attempt}/{connect_attempts})..."
            )
            await asyncio.sleep(delay)

    if last is not None:
        raise last
