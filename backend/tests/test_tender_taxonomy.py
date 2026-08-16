"""Tests for Iran tender document taxonomy catalog."""

from __future__ import annotations

from app.models import DocumentCategory
from app.tender_taxonomy import (
    flatten_taxonomy,
    get_entry,
    get_node,
    legacy_document_category,
    load_taxonomy,
    search_taxonomy,
    taxonomy_stats,
    taxonomy_tree,
)


def test_taxonomy_loads_36_roots():
    data = load_taxonomy()
    assert data.get("schema_version") == 1
    assert data.get("taxonomy_id") == "IR_TENDER_V1"
    assert len(taxonomy_tree()) == 36


def test_all_entries_have_unique_codes():
    stats = taxonomy_stats()
    flat = flatten_taxonomy()
    assert stats["total_codes"] == len(flat)
    assert stats["total_codes"] >= 800
    assert stats["topic_count"] >= 400


def test_get_entry_topic_and_subcategory():
    sub = get_entry("2.1")
    assert sub is not None
    assert sub.kind == "subcategory"
    topic = get_entry("2.1.03")
    assert topic is not None
    assert topic.kind == "topic"
    assert "شرایط عمومی" in topic.title_fa or "General" in topic.title_en


def test_legacy_mapping():
    assert legacy_document_category("2.1.03") == DocumentCategory.TENDER
    assert legacy_document_category("4.2") == DocumentCategory.DRAWING
    assert legacy_document_category("21.05") == DocumentCategory.SCHEDULE
    assert legacy_document_category("27.02") == DocumentCategory.STANDARD


def test_search_finds_general_conditions():
    hits = search_taxonomy("شرایط عمومی")
    assert hits
    assert any(h["kind"] == "topic" for h in hits)


def test_get_node_skips_topics():
    assert get_node("2.1.03") is None
    assert get_node("2.1") is not None
