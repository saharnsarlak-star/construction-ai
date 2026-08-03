"""Union edge predicate vocabulary (Part 5 ∪ Part 6). Stored as free strings (GAP-11)."""

from __future__ import annotations

# Core (Part 6 §2.1) + Part 5 extras (GAP-03) + experience set (Part 6 §2.2)
UNION_PREDICATES: frozenset[str] = frozenset(
    {
        # Part 6 core
        "references",
        "depends_on",
        "belongs_to",
        "located_in",
        "requires",
        "implements",
        "violates",
        "supersedes",
        "conflicts_with",
        "derived_from",
        "approved_by",
        "prepared_by",
        "affects",
        "causes",
        "mitigates",
        "linked_to",
        # Part 5 extras kept first-class
        "amends",
        "quantifies",
        "precedes",
        "lags",
        "governed_by",
        "allocates_responsibility",
        "affects_payment",
        "evidences",
        "gaps",
        "clarifies",
        # Experience
        "learned_from",
        "validated_by",
        "observed_in",
        "resulted_in",
        "applies_to_future_projects",
        "supported_by_experience",
    }
)

# Common party_role values (not a closed DB enum — expand freely)
KNOWN_PARTY_ROLES: frozenset[str] = frozenset(
    {
        "employer",
        "contractor",
        "bidder",
        "consultant",
        "engineer",
        "architect",
        "qs",
        "stakeholder",
        "procuring_entity",
        "unknown",
    }
)


def normalize_predicate(predicate: str) -> str:
    return (predicate or "").strip().lower()


def is_known_predicate(predicate: str) -> bool:
    return normalize_predicate(predicate) in UNION_PREDICATES
