"""Fallback DNS for Supabase when system resolver fails (e.g. Tailscale MagicDNS)."""

from __future__ import annotations

import re
import socket
import subprocess
from functools import lru_cache

# Known Supabase pooler IPv4 (ca-central-1) — used if public DNS lookup also fails.
_KNOWN_POOLER_IPS: dict[str, list[str]] = {
    "aws-0-ca-central-1.pooler.supabase.com": [
        "15.156.180.136",
        "15.156.188.226",
    ],
}

_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_PATCHED = False


@lru_cache(maxsize=16)
def resolve_ipv4(host: str) -> str | None:
    """Resolve hostname to IPv4 — system DNS, then Google DNS, then known fallback."""
    if not host or host.replace(".", "").isdigit():
        return host

    for resolver in (_system_dns, _public_dns_nslookup):
        ip = resolver(host)
        if ip:
            return ip

    fallbacks = _KNOWN_POOLER_IPS.get(host)
    if fallbacks:
        return fallbacks[0]
    return None


def _system_dns(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        return infos[0][4][0]
    except OSError:
        return None


def _public_dns_nslookup(host: str) -> str | None:
    try:
        proc = subprocess.run(
            ["nslookup", host, "8.8.8.8"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        output = proc.stdout or ""
        for line in output.splitlines():
            line = line.strip()
            if line.lower().startswith("address:") and "8.8.8.8" not in line:
                candidate = line.split(":", 1)[1].strip()
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", candidate):
                    return candidate
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def install_supabase_dns_fallback(host: str | None = None) -> str | None:
    """Patch getaddrinfo so Supabase hostnames use a resolved IPv4 when system DNS fails."""
    global _PATCHED

    if not host:
        from urllib.parse import urlparse

        from app.config import settings

        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        host = urlparse(url).hostname or ""

    if not host or "supabase" not in host:
        return None

    ip = resolve_ipv4(host)
    if not ip:
        return None

    if not _PATCHED:

        def _patched_getaddrinfo(*args, **kwargs):
            host_arg = args[0] if args else kwargs.get("host")
            if isinstance(host_arg, str) and "supabase" in host_arg:
                resolved = resolve_ipv4(host_arg) or host_arg
                if resolved != host_arg:
                    new_args = (resolved,) + args[1:] if args else args
                    kwargs = dict(kwargs)
                    kwargs.pop("host", None)
                    return _ORIGINAL_GETADDRINFO(*new_args, **kwargs)
            return _ORIGINAL_GETADDRINFO(*args, **kwargs)

        socket.getaddrinfo = _patched_getaddrinfo  # type: ignore[assignment]
        _PATCHED = True

    if ip != host:
        print(f"DNS fallback active: {host} -> {ip}")
    return ip
