"""Tests for project registry seed data."""

from app.data.project_registry_seed import DEFAULT_IMPLEMENTATION_STEPS, REGISTRY_CATEGORIES


def test_registry_categories_unique_codes():
    codes = [row["code"] for row in REGISTRY_CATEGORIES]
    assert len(codes) == len(set(codes))
    assert len(codes) >= 8


def test_default_steps_unique_codes():
    codes = [row["step_code"] for row in DEFAULT_IMPLEMENTATION_STEPS]
    assert len(codes) == len(set(codes))
    assert len(codes) >= 28


def test_default_steps_sorted():
    orders = [int(row["sort_order"]) for row in DEFAULT_IMPLEMENTATION_STEPS]
    assert orders == sorted(orders)


def test_steps_reference_valid_categories():
    cat_codes = {row["code"] for row in REGISTRY_CATEGORIES}
    for row in DEFAULT_IMPLEMENTATION_STEPS:
        assert row["category"] in cat_codes
