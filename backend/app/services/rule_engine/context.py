"""Parse CDM / document text into structures the PYTHON runners can check."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.models import DocumentCategory, ProjectType


@dataclass
class ScheduleActivity:
    activity_id: str
    name: str
    start: date | None = None
    finish: date | None = None
    duration_days: float | None = None
    total_float: float | None = None
    predecessors: list[str] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    is_milestone: bool = False
    document_name: str = ""
    source_line: str = ""


@dataclass
class BoqLine:
    code: str
    description: str
    qty: float | None
    unit: str
    unit_price: float | None
    total_price: float | None
    document_name: str = ""
    raw: list[str] = field(default_factory=list)


@dataclass
class DocView:
    id: int | None
    category: DocumentCategory
    original_name: str
    extracted_text: str
    content_type: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    canonical: dict[str, Any] = field(default_factory=dict)

    @property
    def subtype(self) -> str:
        return str(self.canonical.get("subtype") or "")

    @property
    def confidence(self) -> float | None:
        from app.services.extractor import get_extraction_confidence

        return get_extraction_confidence(self)


@dataclass
class ElementView:
    id: int
    element_type: str
    name_label: str | None
    type_mark: str | None
    ifc_global_id: str | None
    match_key: str
    document_ids: list[int] = field(default_factory=list)


@dataclass
class RuleContext:
    project_id: int | None
    country: str
    project_type: ProjectType
    documents: list[DocView]
    selected_standards: list[dict[str, Any]] = field(default_factory=list)
    standard_requirements: list[dict[str, Any]] = field(default_factory=list)
    elements: list[ElementView] = field(default_factory=list)
    project_start: date | None = None
    # standard_code -> {edition, is_current, ...} optional library metadata
    standard_versions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def docs(self, *categories: DocumentCategory) -> list[DocView]:
        wanted = set(categories)
        return [d for d in self.documents if d.category in wanted]

    def text_blob(self, *categories: DocumentCategory) -> str:
        return "\n".join(d.extracted_text or "" for d in self.docs(*categories))

    def activities(self) -> list[ScheduleActivity]:
        out: list[ScheduleActivity] = []
        for d in self.docs(DocumentCategory.SCHEDULE):
            out.extend(parse_schedule_activities(d.extracted_text or "", d.original_name))
            # structured activities in CDM/meta if present
            structured = _structured(d)
            for raw in structured.get("activities") or []:
                if isinstance(raw, dict):
                    out.append(_activity_from_dict(raw, d.original_name))
        return out

    def boq_lines(self) -> list[BoqLine]:
        out: list[BoqLine] = []
        for d in self.documents:
            out.extend(parse_boq_from_doc(d))
        return out


def build_doc_view(doc: dict[str, Any]) -> DocView:
    cat = doc.get("category")
    if not isinstance(cat, DocumentCategory):
        cat = DocumentCategory(str(cat))
    meta: dict[str, Any] = {}
    raw_meta = doc.get("meta_json")
    if isinstance(raw_meta, dict):
        meta = raw_meta
    elif isinstance(raw_meta, str) and raw_meta.strip():
        try:
            parsed = json.loads(raw_meta)
            if isinstance(parsed, dict):
                meta = parsed
        except json.JSONDecodeError:
            meta = {}
    canonical = meta.get("canonical") if isinstance(meta.get("canonical"), dict) else {}
    if isinstance(doc.get("canonical"), dict):
        canonical = doc["canonical"]
    return DocView(
        id=doc.get("id"),
        category=cat,
        original_name=str(doc.get("original_name") or ""),
        extracted_text=str(doc.get("extracted_text") or ""),
        content_type=doc.get("content_type"),
        meta=meta,
        canonical=canonical,
    )


def parse_schedule_activities(text: str, document_name: str = "") -> list[ScheduleActivity]:
    """Accept pipe/CSV activity tables and key=value activity blocks."""
    acts: list[ScheduleActivity] = []
    if not text:
        return acts

    # Pipe table: ID|Name|Start|Finish|Duration|Float|Predecessors|Resources|Milestone
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("---"):
            continue
        if "|" in raw and raw.count("|") >= 4:
            parts = [p.strip() for p in raw.split("|")]
            headerish = parts[0].lower() in {"id", "activity", "activity_id", "task"}
            if headerish:
                continue
            act_id = parts[0]
            name = parts[1] if len(parts) > 1 else act_id
            start = _parse_date(parts[2]) if len(parts) > 2 else None
            finish = _parse_date(parts[3]) if len(parts) > 3 else None
            dur = _parse_float(parts[4]) if len(parts) > 4 else None
            fl = _parse_float(parts[5]) if len(parts) > 5 else None
            preds = _split_ids(parts[6]) if len(parts) > 6 else []
            resources = _split_ids(parts[7]) if len(parts) > 7 else []
            is_ms = False
            if len(parts) > 8:
                is_ms = parts[8].lower() in {"1", "true", "yes", "y", "milestone"}
            if dur is None and start and finish:
                dur = float((finish - start).days)
            acts.append(
                ScheduleActivity(
                    activity_id=act_id,
                    name=name,
                    start=start,
                    finish=finish,
                    duration_days=dur,
                    total_float=fl,
                    predecessors=preds,
                    resources=resources,
                    is_milestone=is_ms or "milestone" in name.lower(),
                    document_name=document_name,
                    source_line=raw[:300],
                )
            )

    # Wire successors from predecessor lists
    by_id = {a.activity_id: a for a in acts}
    for a in acts:
        for p in a.predecessors:
            if p in by_id:
                by_id[p].successors.append(a.activity_id)

    # Free-text date + duration clues (supplement)
    if not acts:
        for m in re.finditer(
            r"(?P<id>[A-Z]{0,3}\d{2,5})\s+.*?duration\s*[:=]\s*(?P<dur>-?\d+(?:\.\d+)?)",
            text,
            re.I,
        ):
            acts.append(
                ScheduleActivity(
                    activity_id=m.group("id"),
                    name=m.group("id"),
                    duration_days=float(m.group("dur")),
                    document_name=document_name,
                    source_line=m.group(0)[:300],
                )
            )
    return acts


def parse_boq_from_doc(doc: DocView) -> list[BoqLine]:
    out: list[BoqLine] = []
    for table in doc.canonical.get("tables") or []:
        if not isinstance(table, dict):
            continue
        headers = [str(h).lower() for h in (table.get("headers") or [])]
        if not headers:
            continue
        role = str(table.get("role_hint") or "")
        looks_boq = role == "boq_like" or any(
            h in headers for h in ("qty", "quantity", "unit", "code", "oz")
        )
        if not looks_boq and doc.subtype not in {"gaeb_lv", "excel_boq_candidate"}:
            continue
        idx = {h: i for i, h in enumerate(headers)}

        def col(*names: str) -> int | None:
            for n in names:
                if n in idx:
                    return idx[n]
            return None

        i_code = col("code", "oz", "pos", "item")
        i_desc = col("description", "desc", "text")
        i_qty = col("qty", "quantity")
        i_unit = col("unit", "uom", "qu")
        i_rate = col("unit_price", "rate", "price")
        i_tot = col("total_price", "total", "extension", "amount")
        for row in table.get("rows") or []:
            if not isinstance(row, list):
                continue
            def cell(i: int | None) -> str:
                if i is None or i >= len(row):
                    return ""
                return str(row[i]).strip()

            out.append(
                BoqLine(
                    code=cell(i_code),
                    description=cell(i_desc),
                    qty=_parse_float(cell(i_qty)),
                    unit=cell(i_unit),
                    unit_price=_parse_float(cell(i_rate)),
                    total_price=_parse_float(cell(i_tot)),
                    document_name=doc.original_name,
                    raw=[str(x) for x in row],
                )
            )

    # Pipe fallback — tender/BOQ docs only (never treat schedule activity tables as BOQ)
    if not out and doc.category == DocumentCategory.TENDER:
        lines = [ln.strip() for ln in (doc.extracted_text or "").splitlines() if "|" in ln]
        header = next((ln for ln in lines if ln.lower().startswith("code|")), None)
        if header and header.count("|") >= 4:
            for line in lines:
                if line.lower().startswith("code|") or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                # Require a numeric qty to avoid random pipe prose
                if _parse_float(parts[2] if len(parts) > 2 else None) is None:
                    continue
                out.append(
                    BoqLine(
                        code=parts[0],
                        description=parts[1] if len(parts) > 1 else "",
                        qty=_parse_float(parts[2]) if len(parts) > 2 else None,
                        unit=parts[3] if len(parts) > 3 else "",
                        unit_price=_parse_float(parts[4]) if len(parts) > 4 else None,
                        total_price=_parse_float(parts[5]) if len(parts) > 5 else None,
                        document_name=doc.original_name,
                        raw=parts,
                    )
                )
    return out


_DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"),
]


def extract_dates(text: str) -> list[date]:
    found: list[date] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text or ""):
            try:
                if pat.pattern.startswith(r"\b(\d{4})"):
                    found.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                else:
                    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    # assume D/M/Y when day>12 else try both — prefer D/M/Y for EU
                    if d > 12:
                        found.append(date(y, mo, d))
                    elif mo > 12:
                        found.append(date(y, d, mo))
                    else:
                        found.append(date(y, mo, d))
            except ValueError:
                continue
    return found


def extract_labeled_date(text: str, labels: list[str]) -> date | None:
    lower = text or ""
    for label in labels:
        pat = re.compile(
            rf"{re.escape(label)}\s*[:\-]?\s*(\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[./]\d{{1,2}}[./]\d{{4}})",
            re.I,
        )
        m = pat.search(lower)
        if m:
            dates = extract_dates(m.group(0))
            if dates:
                return dates[0]
    return None


def _structured(doc: DocView) -> dict[str, Any]:
    ext = doc.meta.get("extraction") if isinstance(doc.meta.get("extraction"), dict) else {}
    structured = ext.get("structured") if isinstance(ext.get("structured"), dict) else {}
    return structured


def _activity_from_dict(raw: dict[str, Any], document_name: str) -> ScheduleActivity:
    return ScheduleActivity(
        activity_id=str(raw.get("id") or raw.get("activity_id") or raw.get("name") or "ACT"),
        name=str(raw.get("name") or raw.get("id") or ""),
        start=_parse_date(raw.get("start")),
        finish=_parse_date(raw.get("finish") or raw.get("end")),
        duration_days=_parse_float(raw.get("duration") or raw.get("duration_days")),
        total_float=_parse_float(raw.get("float") or raw.get("total_float")),
        predecessors=_split_ids(raw.get("predecessors") or raw.get("preds") or ""),
        resources=_split_ids(raw.get("resources") or ""),
        is_milestone=bool(raw.get("is_milestone") or raw.get("milestone")),
        document_name=document_name,
        source_line=json.dumps(raw, ensure_ascii=False)[:300],
    )


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    dates = extract_dates(s)
    return dates[0] if dates else None


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in {".", "-", "-."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _split_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [p.strip() for p in re.split(r"[,;/\s]+", str(value)) if p.strip()]
