"""Fixed taxonomy axes for Standards Engine clause tagging.

Country-agnostic vocabulary: stable English ``snake_case`` codes for storage
and lookup; Persian titles are display metadata only.

Axes (four independent dimensions):
  - Discipline — engineering domain (structural, MEP, …)
  - Topic      — subject matter (concrete, seismic_design, …)
  - Element    — building component (column, slab, …)
  - Material   — construction material (reinforced_concrete, …)

To extend a axis, append a member to the corresponding Enum **and** add its
Persian title to ``LABELS_FA`` below.
"""

from __future__ import annotations

import enum
from typing import Final

# ---------------------------------------------------------------------------
# Axis identifier (for generic APIs / DB column grouping)
# ---------------------------------------------------------------------------


class TaxonomyAxis(str, enum.Enum):
    DISCIPLINE = "discipline"
    TOPIC = "topic"
    ELEMENT = "element"
    MATERIAL = "material"


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """SQLAlchemy-compatible value list (matches ``app.models._enum_values``)."""
    return [member.value for member in enum_cls]


# ---------------------------------------------------------------------------
# Taxonomy members — English codes stored in DB
# ---------------------------------------------------------------------------


class Discipline(str, enum.Enum):
    STRUCTURAL = "structural"
    CIVIL = "civil"
    MEP = "mep"
    HSE = "hse"
    ARCHITECTURAL = "architectural"


class Topic(str, enum.Enum):
    CONCRETE = "concrete"
    STEEL = "steel"
    MASONRY = "masonry"
    SEISMIC_DESIGN = "seismic_design"
    FIRE_PROTECTION = "fire_protection"
    EARTHWORK = "earthwork"
    DRAINAGE = "drainage"
    GEOTECHNICAL = "geotechnical"


class Element(str, enum.Enum):
    COLUMN = "column"
    BEAM = "beam"
    SLAB = "slab"
    FOUNDATION = "foundation"
    WALL = "wall"
    DUCT = "duct"
    PIPE = "pipe"


class Material(str, enum.Enum):
    REINFORCED_CONCRETE = "reinforced_concrete"
    STRUCTURAL_STEEL = "structural_steel"
    MASONRY_BLOCK = "masonry_block"
    WOOD = "wood"


# ---------------------------------------------------------------------------
# Persian display titles (keyed by English code string)
# ---------------------------------------------------------------------------

LABELS_FA: Final[dict[TaxonomyAxis, dict[str, str]]] = {
    TaxonomyAxis.DISCIPLINE: {
        Discipline.STRUCTURAL.value: "سازه",
        Discipline.CIVIL.value: "عمران",
        Discipline.MEP.value: "تأسیسات مکانیک و برق",
        Discipline.HSE.value: "ایمنی، بهداشت و محیط‌زیست",
        Discipline.ARCHITECTURAL.value: "معماری",
    },
    TaxonomyAxis.TOPIC: {
        Topic.CONCRETE.value: "بتن",
        Topic.STEEL.value: "فولاد",
        Topic.MASONRY.value: "بنایی",
        Topic.SEISMIC_DESIGN.value: "طراحی لرزه‌ای",
        Topic.FIRE_PROTECTION.value: "حفاظت در برابر آتش",
        Topic.EARTHWORK.value: "خاک‌برداری و خاک‌ریزی",
        Topic.DRAINAGE.value: "زهکشی",
        Topic.GEOTECHNICAL.value: "ژئوتکنیک",
    },
    TaxonomyAxis.ELEMENT: {
        Element.COLUMN.value: "ستون",
        Element.BEAM.value: "تیر",
        Element.SLAB.value: "سقف / دال",
        Element.FOUNDATION.value: "پی",
        Element.WALL.value: "دیوار",
        Element.DUCT.value: "کانال",
        Element.PIPE.value: "لوله",
    },
    TaxonomyAxis.MATERIAL: {
        Material.REINFORCED_CONCRETE.value: "بتن مسلح",
        Material.STRUCTURAL_STEEL.value: "فولاد سازه‌ای",
        Material.MASONRY_BLOCK.value: "بلوک بنایی",
        Material.WOOD.value: "چوب",
    },
}

# Map each axis to its Enum class for generic iteration / validation.
AXIS_ENUM: Final[dict[TaxonomyAxis, type[enum.Enum]]] = {
    TaxonomyAxis.DISCIPLINE: Discipline,
    TaxonomyAxis.TOPIC: Topic,
    TaxonomyAxis.ELEMENT: Element,
    TaxonomyAxis.MATERIAL: Material,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def codes_for_axis(axis: TaxonomyAxis) -> list[str]:
    """All registered English codes for ``axis`` (insertion order preserved)."""
    return enum_values(AXIS_ENUM[axis])


def label_fa(axis: TaxonomyAxis, code: str) -> str | None:
    """Persian display title for ``code``, or ``None`` if unknown."""
    return LABELS_FA.get(axis, {}).get(code)


def label_fa_for(member: enum.Enum) -> str | None:
    """Persian title for an enum member; resolves axis from member class."""
    for axis, enum_cls in AXIS_ENUM.items():
        if isinstance(member, enum_cls):
            return label_fa(axis, member.value)
    return None


def is_valid_code(axis: TaxonomyAxis, code: str) -> bool:
    return code in enum_values(AXIS_ENUM[axis])


def resolve_member(axis: TaxonomyAxis, code: str) -> enum.Enum | None:
    """Return the Enum member for ``code``, or ``None`` if not registered."""
    enum_cls = AXIS_ENUM[axis]
    try:
        return enum_cls(code)
    except ValueError:
        return None


def taxonomy_entry(axis: TaxonomyAxis, member: enum.Enum) -> dict[str, str]:
    """Single row for API/UI: ``{"code": "...", "label_fa": "..."}``."""
    code = member.value
    return {
        "code": code,
        "label_fa": label_fa(axis, code) or code,
    }


def list_axis(axis: TaxonomyAxis) -> list[dict[str, str]]:
    """All entries on ``axis`` as ``code`` + ``label_fa`` dicts."""
    enum_cls = AXIS_ENUM[axis]
    return [taxonomy_entry(axis, member) for member in enum_cls]


__all__ = [
    "AXIS_ENUM",
    "Discipline",
    "Element",
    "LABELS_FA",
    "Material",
    "TaxonomyAxis",
    "Topic",
    "codes_for_axis",
    "enum_values",
    "is_valid_code",
    "label_fa",
    "label_fa_for",
    "list_axis",
    "resolve_member",
    "taxonomy_entry",
]
