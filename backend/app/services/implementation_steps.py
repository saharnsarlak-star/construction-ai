"""Seed implementation_steps table on first boot (delegates to project registry)."""

from app.services.project_registry import seed_implementation_steps

__all__ = ["seed_implementation_steps"]
