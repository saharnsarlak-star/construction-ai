"""Assign stable codes to every taxonomy topic and validate uniqueness.

Run from backend/:
  python scripts/normalize_tender_taxonomy.py
  python scripts/normalize_tender_taxonomy.py --check   # validate only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "app" / "data" / "ir_tender_taxonomy.json"


def split_bilingual(label: str) -> tuple[str, str]:
    text = (label or "").strip()
    for sep in (" — ", " – ", " - "):
        if sep in text:
            fa, en = text.split(sep, 1)
            return fa.strip(), en.strip()
    return text, text


def normalize_topic(parent_code: str, raw, index: int) -> dict:
    seq = f"{index:02d}"
    default_code = f"{parent_code}.{seq}"
    if isinstance(raw, str):
        title_fa, title_en = split_bilingual(raw)
        return {"code": default_code, "title_fa": title_fa, "title_en": title_en}
    if isinstance(raw, dict):
        out = dict(raw)
        out.setdefault("code", default_code)
        out["title_fa"] = str(out.get("title_fa") or out.get("title") or "").strip()
        out["title_en"] = str(out.get("title_en") or out.get("title_fa") or "").strip()
        if not out["title_fa"] and isinstance(raw.get("label"), str):
            out["title_fa"], out["title_en"] = split_bilingual(raw["label"])
        return out
    raise ValueError(f"Invalid topic entry under {parent_code}: {raw!r}")


def normalize_node(raw: dict) -> dict:
    code = str(raw.get("code") or "").strip()
    if not code:
        raise ValueError("Category missing code")
    out = {
        "code": code,
        "title_fa": str(raw.get("title_fa") or "").strip(),
        "title_en": str(raw.get("title_en") or "").strip(),
        "subcategories": [],
        "topics": [],
    }
    legacy_items = raw.get("topics") or raw.get("items") or []
    out["topics"] = [normalize_topic(code, item, i + 1) for i, item in enumerate(legacy_items)]
    out["subcategories"] = [normalize_node(sub) for sub in (raw.get("subcategories") or [])]
    return out


def collect_codes(categories: list[dict]) -> dict[str, str]:
    seen: dict[str, str] = {}

    def reg(code: str, path: str) -> None:
        if code in seen:
            raise ValueError(f"Duplicate code {code}: {seen[code]} vs {path}")
        seen[code] = path

    def walk(node: dict, path: str) -> None:
        reg(node["code"], path)
        for topic in node.get("topics") or []:
            reg(topic["code"], f"{path} / {topic.get('title_fa') or topic['code']}")
        for sub in node.get("subcategories") or []:
            walk(sub, f"{path} > {sub.get('title_fa') or sub['code']}")

    for cat in categories:
        walk(cat, cat.get("title_fa") or cat["code"])
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Validate only; do not write")
    args = parser.parse_args()

    raw = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    categories = [normalize_node(cat) for cat in (raw.get("categories") or [])]
    codes = collect_codes(categories)

    out = {
        "schema_version": int(raw.get("schema_version") or 1),
        "taxonomy_id": str(raw.get("taxonomy_id") or "IR_TENDER_V1"),
        "taxonomy_name": raw.get("taxonomy_name") or "",
        "language": raw.get("language") or "fa/en",
        "code_format": "root=NN | sub=NN.N | topic=NN.N.NN (extend by appending .NN or new roots)",
        "categories": categories,
    }

    topic_count = sum(1 for c in codes if c.count(".") >= 2 or (c.count(".") == 1 and len(c.split(".")[-1]) == 2))
    print(f"categories={len(categories)} unique_codes={len(codes)} topics~={sum(len(n.get('topics') or []) for n in categories)}")

    if args.check:
        print("OK — taxonomy valid")
        return 0

    TAXONOMY_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {TAXONOMY_PATH}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
