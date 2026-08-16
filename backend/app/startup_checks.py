"""Startup warnings for insecure or misconfigured deployments."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_INSECURE_PASSWORDS = frozenset({"Admin123!", "User123!", "admin", "password"})
_INSECURE_TOKENS = frozenset({"dev-admin-token", "dev-user-token"})


def run_startup_checks() -> list[str]:
    warnings: list[str] = []
    db = settings.database_url or ""
    is_sqlite = db.startswith("sqlite")
    is_postgres = "postgresql" in db

    if is_sqlite:
        warnings.append(
            "DATABASE_URL is SQLite — use Supabase/Postgres in production."
        )
    if settings.admin_password in _INSECURE_PASSWORDS:
        warnings.append("ADMIN_PASSWORD is a default dev password — change for production.")
    if settings.user_password in _INSECURE_PASSWORDS:
        warnings.append("USER_PASSWORD is a default dev password — change for production.")
    if settings.admin_api_token in _INSECURE_TOKENS:
        warnings.append("ADMIN_API_TOKEN is a default dev token — change for production.")
    if settings.max_upload_mb <= 0:
        warnings.append("MAX_UPLOAD_MB=0 (unlimited uploads) — set a cap in production.")

    intelligence_off = not any(
        [
            settings.new_rule_engine_enabled,
            settings.ai_rule_engine_enabled,
            settings.knowledge_graph_enabled,
            settings.ti_semantic_standards_enabled,
        ]
    )
    if intelligence_off and is_postgres:
        warnings.append(
            "All intelligence flags OFF — analyze uses keyword heuristics only. "
            "Enable TI/AI/PYTHON/KG as needed."
        )

    for msg in warnings:
        logger.warning("[startup] %s", msg)
    return warnings
