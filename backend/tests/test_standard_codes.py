"""Tests for stable standard family / slot codes."""

from app.tender_taxonomy.standard_codes import (
    CODE55_FAMILY,
    clause_slot_code,
    color_index_for_taxonomy,
    resolve_family_code,
    section_slot_code,
    taxonomy_parts,
    taxonomy_subcode,
)


def test_resolve_code55_family():
    assert resolve_family_code(standard_code="CODE55-VOL1-IR") == CODE55_FAMILY
    assert resolve_family_code(standard_code="NBC-03", title="ضابطه شماره ۵۵") == CODE55_FAMILY


def test_taxonomy_subcode():
    assert taxonomy_subcode("20.3.01") == "20.3"
    assert taxonomy_subcode("14.12") == "14.12"


def test_taxonomy_parts():
    assert taxonomy_parts("20.3.01") == ("20", "20.3", "20.3.01")
    assert taxonomy_parts("14.12") == ("14", "14.12", None)


def test_clause_slot_code_stable():
    slot = clause_slot_code(CODE55_FAMILY, "20.3.01", "2-2-3-1")
    assert slot.startswith(f"{CODE55_FAMILY}::20.3.01::")
    assert slot == clause_slot_code(CODE55_FAMILY, "20.3.01", "2-2-3-1")


def test_section_slot_code():
    sec = section_slot_code(CODE55_FAMILY, "20.3", "2-2")
    assert "SEC-2-2" in sec


def test_color_index_range():
    assert 0 <= color_index_for_taxonomy("20.3.01") <= 11
