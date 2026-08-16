"""Stable standard-family and clause slot codes derived from IR tender taxonomy.

Slot codes stay fixed across document editions so a new Code55 revision can
replace clause content without breaking project references.
"""

from __future__ import annotations

import re

CODE55_FAMILY = "IR-STD-55"
_SLOT_SEP = "::"

_CODE55_MARKERS = (
    "code55",
    "code-55",
    "code_55",
    "ضابطه شماره ۵۵",
    "ضابطه شماره 55",
    "استاندارد 55",
    "استاندارد ۵۵",
)


def normalize_clause_ref(value: str) -> str:
    """Normalize clause/section numbers for stable slot keys."""
    s = (value or "").strip()
    s = s.replace("–", "-").replace("—", "-").replace(".", "-")
    s = re.sub(r"[^\d\-a-zA-Z\u0600-\u06ff]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "0"


def taxonomy_root_code(taxonomy_code: str | None) -> str | None:
    code = (taxonomy_code or "").strip()
    if not code:
        return None
    return code.split(".", 1)[0]


def taxonomy_parts(taxonomy_code: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (category, subcategory, topic) codes for a mapped taxonomy code."""
    code = (taxonomy_code or "").strip()
    if not code:
        return None, None, None
    parts = code.split(".")
    root = parts[0]
    if len(parts) == 1:
        return root, None, None
    if len(parts) == 2:
        return root, code, None
    sub = ".".join(parts[:2])
    return root, sub, code


def taxonomy_subcode(taxonomy_code: str | None) -> str | None:
    """Map topic code ``20.3.01`` → subcategory ``20.3``; ``14.12`` → ``14.12``."""
    code = (taxonomy_code or "").strip()
    if not code:
        return None
    parts = code.split(".")
    if len(parts) >= 3:
        return ".".join(parts[:2])
    return code


def resolve_family_code(
    *,
    standard_code: str,
    title: str = "",
    original_name: str = "",
    explicit: str | None = None,
) -> str:
    """Return stable family code for a catalog standard (edition-independent)."""
    if explicit and explicit.strip():
        return explicit.strip().upper()

    blob = f"{standard_code} {title} {original_name}".lower()
    code_up = (standard_code or "").upper()

    if any(m in blob for m in _CODE55_MARKERS) or re.search(r"(^|[^0-9])55([^0-9]|$)", blob):
        return CODE55_FAMILY
    if "CODE55" in code_up or re.search(r"STD-?55|55-STD", code_up):
        return CODE55_FAMILY

    num = re.search(r"(\d{1,4})", standard_code or "")
    if num:
        return f"IR-STD-{num.group(1)}"

    slug = re.sub(r"[^A-Z0-9]+", "-", code_up).strip("-")[:24] or "UNKNOWN"
    return f"IR-STD-{slug}"


def clause_slot_code(
    family_code: str,
    taxonomy_code: str | None,
    clause_number: str,
) -> str:
    """Stable per-clause identifier: family + taxonomy topic + clause ref."""
    fam = (family_code or "IR-STD-UNKNOWN").strip().upper()
    tax = (taxonomy_code or "00.0.00").strip()
    ref = normalize_clause_ref(clause_number)
    return f"{fam}{_SLOT_SEP}{tax}{_SLOT_SEP}{ref}"


def section_slot_code(
    family_code: str,
    taxonomy_subcode: str | None,
    section: str,
) -> str:
    """Stable per-section identifier under a taxonomy subcategory."""
    fam = (family_code or "IR-STD-UNKNOWN").strip().upper()
    tax = (taxonomy_subcode or "00.0").strip()
    ref = normalize_clause_ref(section)
    return f"{fam}{_SLOT_SEP}{tax}{_SLOT_SEP}SEC-{ref}"


def color_index_for_taxonomy(taxonomy_code: str | None) -> int:
    """Deterministic palette index (0–11) from taxonomy subcategory."""
    sub = taxonomy_subcode(taxonomy_code) or "0"
    total = 0
    for ch in sub:
        if ch.isdigit():
            total = total * 10 + int(ch)
        elif ch == ".":
            total += 17
        else:
            total += ord(ch)
    return total % 12
