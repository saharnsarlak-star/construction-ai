"""Tender ↔ standard compliance checks (Phase 2 bridge)."""

from app.standards_engine.compliance.gap_checker import (
    CoverageGap,
    check_requirement_coverage,
    check_standard_coverage,
)

__all__ = [
    "CoverageGap",
    "check_requirement_coverage",
    "check_standard_coverage",
]
