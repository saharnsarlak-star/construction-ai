"""IFC (Industry Foundation Classes) native extraction via IfcOpenShell.

Metadata / property-oriented only — no mesh or geometry evaluation.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.normalized_extraction import NormalizedExtractionResult

logger = logging.getLogger(__name__)

# Safeguards (architecture: avoid Railway timeouts on huge models)
IFC_MAX_FILE_BYTES = int(os.environ.get("IFC_MAX_FILE_BYTES", str(50 * 1024 * 1024)))
IFC_MAX_ELEMENTS_FULL_PSET = int(os.environ.get("IFC_MAX_ELEMENTS_FULL_PSET", "2500"))
IFC_MAX_HIGHLIGHTS = 200
IFC_MAX_MERGED_CHARS = 120_000

# Representative discipline-relevant IFC classes (not exhaustive)
_DISCIPLINE_TYPES: dict[str, tuple[str, ...]] = {
    "architecture": (
        "IfcWall",
        "IfcWallStandardCase",
        "IfcSlab",
        "IfcRoof",
        "IfcDoor",
        "IfcWindow",
        "IfcStair",
        "IfcRailing",
        "IfcCurtainWall",
        "IfcCovering",
        "IfcSpace",
    ),
    "structure": (
        "IfcBeam",
        "IfcColumn",
        "IfcMember",
        "IfcFooting",
        "IfcPile",
        "IfcPlate",
        "IfcReinforcingBar",
        "IfcReinforcingMesh",
    ),
    "mep_hvac": (
        "IfcDuctSegment",
        "IfcDuctFitting",
        "IfcAirTerminal",
        "IfcFlowTerminal",
        "IfcFan",
        "IfcPump",
        "IfcBoiler",
        "IfcChiller",
        "IfcUnitaryEquipment",
    ),
    "mep_plumbing": (
        "IfcPipeSegment",
        "IfcPipeFitting",
        "IfcSanitaryTerminal",
        "IfcWasteTerminal",
        "IfcTank",
    ),
    "mep_electrical": (
        "IfcCableSegment",
        "IfcCableCarrierSegment",
        "IfcLightFixture",
        "IfcElectricDistributionBoard",
        "IfcOutlet",
        "IfcSwitchingDevice",
        "IfcProtectiveDevice",
    ),
    "fire_life_safety": (
        "IfcFireSuppressionTerminal",
        "IfcAlarm",
        "IfcSensor",
    ),
}

_PSET_HINTS = (
    "fire",
    "brand",
    "material",
    "load",
    "bearing",
    "structural",
    "acoustic",
    "thermal",
    "resistance",
    "rating",
    "حریق",
    "ماده",
)


def extract_ifc(path: str | Path) -> NormalizedExtractionResult:
    """Parse an IFC file into structured metadata + corpus text."""
    path = Path(path)
    notes: list[str] = []

    try:
        import ifcopenshell
        import ifcopenshell.util.element
    except ImportError as exc:
        return NormalizedExtractionResult(
            merged_text=f"[IFC_ERROR] {path.name}\nIfcOpenShell not installed: {exc}",
            extraction_method="ifc_native",
            confidence_score=0.0,
            structured={},
            needs_manual_review=True,
            error=str(exc),
            notes=["Install ifcopenshell to enable IFC extraction"],
        )

    try:
        size = path.stat().st_size
    except OSError as exc:
        return _fail(path, f"Cannot stat file: {exc}")

    if size > IFC_MAX_FILE_BYTES:
        notes.append(
            f"Large IFC ({size} bytes > {IFC_MAX_FILE_BYTES}); "
            "metadata-only path, no geometry/mesh, capped property walk."
        )

    try:
        # ifcopenshell.open reads SPF/XML; never invoke geometry iterators here.
        model = ifcopenshell.open(str(path))
    except Exception as exc:  # noqa: BLE001
        logger.exception("IFC open failed: %s", path.name)
        return _fail(path, f"Failed to open IFC ({exc})")

    try:
        schema = getattr(model, "schema", None) or "unknown"
        spatial_hierarchy = _spatial_hierarchy(model)
        elements_by_discipline, total_elements = _count_elements(model)
        property_highlights, pset_notes = _property_highlights(
            model,
            ifcopenshell.util.element,
            total_elements=total_elements,
            file_bytes=size,
        )
        notes.extend(pset_notes)

        structured: dict[str, Any] = {
            "schema": str(schema),
            "file_bytes": size,
            "spatial_hierarchy": spatial_hierarchy,
            "elements_by_discipline": elements_by_discipline,
            "element_count_total": total_elements,
            "property_highlights": property_highlights,
            "geometry_processed": False,
        }

        merged = _build_merged_text(path.name, structured)
        confidence = 96.0 if total_elements or spatial_hierarchy else 90.0
        if size > IFC_MAX_FILE_BYTES or total_elements > IFC_MAX_ELEMENTS_FULL_PSET:
            confidence = min(confidence, 92.0)

        if not merged.strip() or merged.startswith("[IFC_EMPTY]"):
            return NormalizedExtractionResult(
                merged_text=merged or f"[IFC_EMPTY] {path.name}\nNo IFC entities extracted.",
                extraction_method="ifc_native",
                confidence_score=0.0,
                structured=structured,
                needs_manual_review=True,
                error="No extractable IFC metadata",
                notes=notes,
            )

        return NormalizedExtractionResult(
            merged_text=merged,
            extraction_method="ifc_native",
            confidence_score=confidence,
            structured=structured,
            needs_manual_review=False,
            error=None,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("IFC parse failed: %s", path.name)
        return _fail(path, f"IFC parse error: {exc}")


def _fail(path: Path, message: str) -> NormalizedExtractionResult:
    return NormalizedExtractionResult(
        merged_text=f"[IFC_ERROR] {path.name}\n{message}",
        extraction_method="ifc_native",
        confidence_score=0.0,
        structured={},
        needs_manual_review=True,
        error=message,
        notes=[],
    )


def _entity_name(el: Any) -> str:
    name = getattr(el, "Name", None) or ""
    long_name = getattr(el, "LongName", None) or ""
    parts = [p for p in (name, long_name) if p]
    return " — ".join(parts) if parts else (getattr(el, "GlobalId", None) or "unnamed")


def _spatial_hierarchy(model: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def add(kind: str, el: Any, parent: str | None = None) -> None:
        nodes.append(
            {
                "type": kind,
                "name": _entity_name(el),
                "global_id": getattr(el, "GlobalId", None),
                "parent_global_id": parent,
            }
        )

    projects = list(model.by_type("IfcProject") or [])
    for project in projects:
        add("IfcProject", project)
        pid = getattr(project, "GlobalId", None)
        # Prefer decomposition when available
        for site in model.by_type("IfcSite") or []:
            add("IfcSite", site, pid)
            sid = getattr(site, "GlobalId", None)
            for building in model.by_type("IfcBuilding") or []:
                add("IfcBuilding", building, sid)
                bid = getattr(building, "GlobalId", None)
                for storey in model.by_type("IfcBuildingStorey") or []:
                    add("IfcBuildingStorey", storey, bid)
                    stid = getattr(storey, "GlobalId", None)
                    # Spaces are many; list names only (cap)
                    spaces = list(model.by_type("IfcSpace") or [])[:80]
                    for space in spaces:
                        add("IfcSpace", space, stid)
        # If no site, still list buildings/storeys
        if not (model.by_type("IfcSite") or []):
            for building in model.by_type("IfcBuilding") or []:
                add("IfcBuilding", building, pid)
            for storey in model.by_type("IfcBuildingStorey") or []:
                add("IfcBuildingStorey", storey, pid)

    # Dedupe by global_id+type
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for n in nodes:
        key = f"{n.get('type')}:{n.get('global_id')}:{n.get('name')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
    return unique


def _count_elements(model: Any) -> tuple[dict[str, dict[str, int]], int]:
    by_disc: dict[str, dict[str, int]] = {}
    total = 0
    for discipline, types in _DISCIPLINE_TYPES.items():
        counts: dict[str, int] = {}
        for tname in types:
            try:
                ents = model.by_type(tname) or []
            except Exception:  # noqa: BLE001
                ents = []
            n = len(ents)
            if n:
                counts[tname] = n
                total += n
        if counts:
            by_disc[discipline] = counts
    return by_disc, total


def _property_highlights(
    model: Any,
    element_util: Any,
    *,
    total_elements: int,
    file_bytes: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    highlights: list[dict[str, Any]] = []

    capped = total_elements > IFC_MAX_ELEMENTS_FULL_PSET or file_bytes > IFC_MAX_FILE_BYTES
    if capped:
        notes.append(
            f"Property walk capped (elements={total_elements}, bytes={file_bytes}); "
            "geometry/mesh never processed."
        )

    # Prefer walls/slabs/doors/columns for fire/material/load hints
    priority_types = (
        "IfcWall",
        "IfcWallStandardCase",
        "IfcSlab",
        "IfcDoor",
        "IfcColumn",
        "IfcBeam",
        "IfcCovering",
        "IfcSpace",
    )
    scanned = 0
    max_scan = 400 if capped else IFC_MAX_ELEMENTS_FULL_PSET

    for tname in priority_types:
        try:
            ents = list(model.by_type(tname) or [])
        except Exception:  # noqa: BLE001
            continue
        for el in ents:
            if scanned >= max_scan or len(highlights) >= IFC_MAX_HIGHLIGHTS:
                break
            scanned += 1
            try:
                psets = element_util.get_psets(el) or {}
            except Exception:  # noqa: BLE001
                continue
            interesting = _filter_interesting_psets(psets)
            if not interesting:
                continue
            highlights.append(
                {
                    "type": el.is_a(),
                    "name": _entity_name(el),
                    "global_id": getattr(el, "GlobalId", None),
                    "properties": interesting,
                }
            )
        if len(highlights) >= IFC_MAX_HIGHLIGHTS:
            break

    notes.append("geometry_processed=false")
    return highlights, notes


def _filter_interesting_psets(psets: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pset_name, props in (psets or {}).items():
        if not isinstance(props, dict):
            continue
        name_l = str(pset_name).lower()
        keep_props: dict[str, Any] = {}
        for k, v in props.items():
            if k in {"id", "type"}:
                continue
            blob = f"{pset_name} {k} {v}".lower()
            if any(h in blob for h in _PSET_HINTS) or any(h in name_l for h in _PSET_HINTS):
                keep_props[str(k)] = _jsonable(v)
        if keep_props:
            out[str(pset_name)] = keep_props
    return out


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _build_merged_text(filename: str, structured: dict[str, Any]) -> str:
    lines: list[str] = [
        f"--- ifc: {filename} (IFC_NATIVE) ---",
        f"Schema: {structured.get('schema')}",
        f"Elements (typed count): {structured.get('element_count_total', 0)}",
        "Geometry: not processed (metadata only)",
        "",
        "Spatial hierarchy:",
    ]
    spatial = structured.get("spatial_hierarchy") or []
    if not spatial:
        lines.append("  (none)")
    for node in spatial[:120]:
        lines.append(
            f"  - {node.get('type')}: {node.get('name')}"
        )

    lines.append("")
    lines.append("Elements by discipline:")
    by_disc = structured.get("elements_by_discipline") or {}
    if not by_disc:
        lines.append("  (none of the tracked IFC types found)")
    for disc, counts in by_disc.items():
        parts = ", ".join(f"{k}={v}" for k, v in counts.items())
        lines.append(f"  [{disc}] {parts}")
        # Topic keywords for rule engine
        lines.append(f"  keywords: {disc} " + " ".join(counts.keys()))

    lines.append("")
    lines.append("Property highlights (fire/material/load-related):")
    highlights = structured.get("property_highlights") or []
    if not highlights:
        lines.append("  (none matched)")
    for h in highlights[:80]:
        lines.append(f"  - {h.get('type')} {h.get('name')}: {h.get('properties')}")

    text = "\n".join(lines).strip()
    if len(text) > IFC_MAX_MERGED_CHARS:
        text = text[:IFC_MAX_MERGED_CHARS] + "\n[IFC_TRUNCATED]"
    if structured.get("element_count_total", 0) == 0 and not spatial:
        return f"[IFC_EMPTY] {filename}\n{text}"
    return text
