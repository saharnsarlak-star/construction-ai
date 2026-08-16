"""Load, validate, and query the extensible Iran tender document taxonomy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.models import DocumentCategory

_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "ir_tender_taxonomy.json"
_EXTENSIONS_DIR = _TAXONOMY_PATH.parent / "taxonomy_extensions"

_DRAWING_ROOTS = frozenset({"4", "31"})
_SCHEDULE_ROOTS = frozenset({"21"})
_STANDARD_ROOTS = frozenset({"27"})

TaxonomyKind = Literal["category", "subcategory", "topic"]


@dataclass(frozen=True)
class TaxonomyTopic:
    code: str
    title_fa: str
    title_en: str
    parent_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title_fa": self.title_fa,
            "title_en": self.title_en,
            "parent_code": self.parent_code,
            "kind": "topic",
            "legacy_category": legacy_document_category(self.code).value,
        }


@dataclass(frozen=True)
class TaxonomyNode:
    code: str
    title_fa: str
    title_en: str
    topics: tuple[TaxonomyTopic, ...] = ()
    subcategories: tuple["TaxonomyNode", ...] = ()
    parent_code: str | None = None
    kind: TaxonomyKind = "category"

    def to_dict(self, *, include_children: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "title_fa": self.title_fa,
            "title_en": self.title_en,
            "kind": self.kind,
            "legacy_category": legacy_document_category(self.code).value,
            "topics": [t.to_dict() for t in self.topics],
            # Backward-compatible string list for older clients.
            "items": [f"{t.title_fa} — {t.title_en}" for t in self.topics],
        }
        if include_children:
            out["subcategories"] = [c.to_dict(include_children=True) for c in self.subcategories]
        return out


@dataclass(frozen=True)
class TaxonomyEntry:
    """Flat index row — category, subcategory, or leaf topic."""

    code: str
    title_fa: str
    title_en: str
    parent_code: str | None
    kind: TaxonomyKind
    path_fa: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title_fa": self.title_fa,
            "title_en": self.title_en,
            "parent_code": self.parent_code,
            "kind": self.kind,
            "path_fa": self.path_fa,
            "legacy_category": legacy_document_category(self.code).value,
        }


def split_bilingual(label: str) -> tuple[str, str]:
    text = (label or "").strip()
    for sep in (" — ", " – ", " - "):
        if sep in text:
            fa, en = text.split(sep, 1)
            return fa.strip(), en.strip()
    return text, text


def _parse_topic(parent_code: str, raw: Any, index: int) -> TaxonomyTopic:
    seq = f"{index:02d}"
    default_code = f"{parent_code}.{seq}"
    if isinstance(raw, str):
        title_fa, title_en = split_bilingual(raw)
        return TaxonomyTopic(code=default_code, title_fa=title_fa, title_en=title_en, parent_code=parent_code)
    if isinstance(raw, dict):
        code = str(raw.get("code") or default_code).strip()
        title_fa = str(raw.get("title_fa") or raw.get("title") or "").strip()
        title_en = str(raw.get("title_en") or title_fa).strip()
        if not title_fa and isinstance(raw.get("label"), str):
            title_fa, title_en = split_bilingual(raw["label"])
        return TaxonomyTopic(code=code, title_fa=title_fa, title_en=title_en, parent_code=parent_code)
    raise ValueError(f"Invalid topic under {parent_code}: {raw!r}")


def _parse_node(raw: dict[str, Any], *, parent_code: str | None = None, depth: int = 0) -> TaxonomyNode:
    code = str(raw.get("code") or "").strip()
    if not code:
        raise ValueError("Taxonomy node missing code")
    kind: TaxonomyKind = "category" if depth == 0 else "subcategory"
    legacy_items = raw.get("topics") or raw.get("items") or []
    topics = tuple(_parse_topic(code, item, i + 1) for i, item in enumerate(legacy_items))
    subs = tuple(
        _parse_node(sub, parent_code=code, depth=depth + 1)
        for sub in (raw.get("subcategories") or [])
    )
    return TaxonomyNode(
        code=code,
        title_fa=str(raw.get("title_fa") or "").strip(),
        title_en=str(raw.get("title_en") or "").strip(),
        topics=topics,
        subcategories=subs,
        parent_code=parent_code,
        kind=kind,
    )


def _load_extension_categories() -> list[dict[str, Any]]:
    if not _EXTENSIONS_DIR.is_dir():
        return []
    extra: list[dict[str, Any]] = []
    for path in sorted(_EXTENSIONS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("categories"), list):
            extra.extend(data["categories"])
        if isinstance(data.get("append_categories"), list):
            extra.extend(data["append_categories"])
    return extra


def _validate_unique_codes(roots: tuple[TaxonomyNode, ...]) -> None:
    seen: dict[str, str] = {}

    def reg(code: str, path: str) -> None:
        if code in seen:
            raise ValueError(f"Duplicate taxonomy code {code!r} ({seen[code]} vs {path})")
        seen[code] = path

    def walk(node: TaxonomyNode, path: str) -> None:
        reg(node.code, path)
        for topic in node.topics:
            reg(topic.code, f"{path} / {topic.title_fa}")
        for sub in node.subcategories:
            walk(sub, f"{path} > {sub.title_fa}")

    for root in roots:
        walk(root, root.title_fa or root.code)


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    data = json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))
    categories = list(data.get("categories") or [])
    categories.extend(_load_extension_categories())
    data = {**data, "categories": categories}
    return data


@lru_cache(maxsize=1)
def taxonomy_tree() -> tuple[TaxonomyNode, ...]:
    data = load_taxonomy()
    roots = tuple(_parse_node(cat, depth=0) for cat in (data.get("categories") or []))
    _validate_unique_codes(roots)
    return roots


@lru_cache(maxsize=1)
def _flat_index() -> dict[str, TaxonomyEntry]:
    out: dict[str, TaxonomyEntry] = {}

    def walk(node: TaxonomyNode, path_fa: str) -> None:
        out[node.code] = TaxonomyEntry(
            code=node.code,
            title_fa=node.title_fa,
            title_en=node.title_en,
            parent_code=node.parent_code,
            kind=node.kind,
            path_fa=path_fa,
        )
        for topic in node.topics:
            out[topic.code] = TaxonomyEntry(
                code=topic.code,
                title_fa=topic.title_fa,
                title_en=topic.title_en,
                parent_code=topic.parent_code,
                kind="topic",
                path_fa=f"{path_fa} / {topic.title_fa}",
            )
        for sub in node.subcategories:
            walk(sub, f"{path_fa} > {sub.title_fa}")

    for root in taxonomy_tree():
        walk(root, root.title_fa or root.code)
    return out


def get_node(code: str) -> TaxonomyNode | None:
    """Structural node only (category / subcategory)."""
    entry = _flat_index().get(code.strip())
    if entry is None or entry.kind == "topic":
        return None
    # Re-walk tree for full node — cheap for single lookup at upload time.
    target = code.strip()

    def find(nodes: tuple[TaxonomyNode, ...]) -> TaxonomyNode | None:
        for node in nodes:
            if node.code == target:
                return node
            found = find(node.subcategories)
            if found:
                return found
        return None

    return find(taxonomy_tree())


def get_entry(code: str) -> TaxonomyEntry | None:
    return _flat_index().get((code or "").strip())


def flatten_taxonomy() -> list[dict[str, Any]]:
    return [e.to_dict() for e in sorted(_flat_index().values(), key=lambda x: x.code)]


def taxonomy_stats() -> dict[str, int]:
    entries = _flat_index().values()
    return {
        "category_count": sum(1 for e in entries if e.kind == "category"),
        "subcategory_count": sum(1 for e in entries if e.kind == "subcategory"),
        "topic_count": sum(1 for e in entries if e.kind == "topic"),
        "total_codes": len(entries),
    }


def _root_code(code: str) -> str:
    return (code or "").split(".", 1)[0]


def legacy_document_category(code: str | None) -> DocumentCategory:
    if not code:
        return DocumentCategory.TENDER
    root = _root_code(code)
    if root in _DRAWING_ROOTS:
        return DocumentCategory.DRAWING
    if root in _SCHEDULE_ROOTS:
        return DocumentCategory.SCHEDULE
    if root in _STANDARD_ROOTS:
        return DocumentCategory.STANDARD
    return DocumentCategory.TENDER


def _normalize(text: str) -> str:
    text = text.strip().lower()
    return re.sub(r"\s+", " ", text)


def warm_taxonomy_cache() -> None:
    """Pre-build taxonomy indexes and API payloads (call once at startup)."""
    taxonomy_tree()
    taxonomy_tree_response()
    taxonomy_flat_response()


def _meta_dict() -> dict[str, Any]:
    raw = load_taxonomy()
    stats = taxonomy_stats()
    return {
        "schema_version": int(raw.get("schema_version") or 1),
        "taxonomy_id": str(raw.get("taxonomy_id") or ""),
        "taxonomy_name": str(raw.get("taxonomy_name") or ""),
        "language": str(raw.get("language") or "fa/en"),
        "code_format": str(raw.get("code_format") or ""),
        "category_count": stats["category_count"],
        "subcategory_count": stats["subcategory_count"],
        "topic_count": stats["topic_count"],
        "total_codes": stats["total_codes"],
    }


@lru_cache(maxsize=1)
def taxonomy_tree_response() -> dict[str, Any]:
    roots = taxonomy_tree()
    return {
        "meta": _meta_dict(),
        "categories": [n.to_dict(include_children=True) for n in roots],
    }


@lru_cache(maxsize=1)
def taxonomy_flat_response() -> dict[str, Any]:
    return {
        "meta": _meta_dict(),
        "entries": flatten_taxonomy(),
    }


@lru_cache(maxsize=1)
def taxonomy_tree_json() -> str:
    return json.dumps(taxonomy_tree_response(), ensure_ascii=False)


def search_taxonomy(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    q = _normalize(query)
    if not q:
        return []
    hits: list[tuple[int, dict[str, Any]]] = []

    def score(*labels: str) -> int:
        best = 0
        for label in labels:
            t = _normalize(label)
            if q in t:
                best = max(best, 100 + len(q))
            parts = [p for p in re.split(r"[\s—\-/]+", q) if len(p) >= 2]
            best = max(best, sum(10 for p in parts if p in t))
        return best

    for entry in _flat_index().values():
        best = score(entry.title_fa, entry.title_en, entry.path_fa, entry.code)
        if best <= 0:
            continue
        hits.append((best, entry.to_dict()))
    hits.sort(key=lambda x: (-x[0], x[1]["code"]))
    return [h[1] for h in hits[:limit]]
