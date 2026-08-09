"""Tender risk analysis engine — gated extraction, semantic standards, 3-tier findings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.knowledge.country_profiles import get_country_profile, profile_snapshot
from app.knowledge.document_templates import resolve_document_template
from app.knowledge.prompt_templates import render_prompt_bundle
from app.knowledge.rules_registry import RuleDef, resolve_rules_for_project
from app.knowledge.standards_catalog import get_standard
from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType, RiskSeverity
from app.services.extractor import (
    clean_display_excerpt,
    document_has_extraction_limitation,
    has_low_extraction_confidence,
    has_usable_text,
    sentence_around_index,
    strip_extraction_chrome,
    verbatim_document_excerpt,
)

# Below this success rate → block full analysis (no confident risk claims).
_EXTRACTION_HARD_GATE = 0.50
# Between hard gate and this → proceed with caveats.
_EXTRACTION_SOFT_GATE = 0.90


@dataclass
class RiskFinding:
    code: str
    category: str  # thematic: scope, compliance, …
    severity: RiskSeverity
    title: str
    description: str
    recommendation: str
    financial_impact: str | None = None
    schedule_impact: str | None = None
    evidence: str | None = None
    finding_category: str = "risk"  # risk | limitation | methodology | experience
    risk_score: int | None = None
    source_excerpt: str | None = None
    cause_effect_chain: list[str] = field(default_factory=list)
    data_completeness_caveat: str | None = None
    estimated_impact: str | None = None
    # Phase 3+: rule_based | llm_based | hybrid | experience_based (None = legacy keyword)
    source_layer: str | None = None
    # Phase 4: model confidence 0–100 (distinct from risk_score severity proxy)
    confidence_score: int | None = None
    # Source attribution for report cards
    source_document_name: str | None = None
    source_page: int | None = None


def parse_source_page(location: str | None) -> int | None:
    """Extract a page number from free-text location strings (page 3 / صفحه ۴ / p.12)."""
    if not location:
        return None
    text = str(location).strip()
    patterns = (
        r"(?:page|صفحه|seite|pg\.?|p\.?)\s*[:=\-]?\s*(\d{1,4})",
        r"^\s*(\d{1,4})\s*$",
    )
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 9999:
                    return n
            except ValueError:
                continue
    return None


def estimate_page_at_index(text: str, index: int) -> int:
    """Best-effort page estimate from form-feeds or ~1800 chars/page (PDF-ish)."""
    if index < 0:
        index = 0
    before = text[:index]
    feeds = before.count("\f")
    if feeds:
        return feeds + 1
    markers = list(
        re.finditer(r"(?:^|\n)\s*(?:صفحه|page|seite)\s*[:=\-]?\s*(\d{1,4})", before, re.IGNORECASE | re.MULTILINE)
    )
    if markers:
        try:
            return int(markers[-1].group(1))
        except ValueError:
            pass
    # Typical tender PDF ~1500–2000 chars/page after extraction
    return max(1, index // 1800 + 1)


def _normalize_fa_search(text: str) -> str:
    """Normalize Persian/Arabic letters and whitespace for fuzzy containment search."""
    t = (text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _raw_keyword_index(text: str, keyword_norm: str) -> int:
    """Find ``keyword_norm`` inside raw text; return start index or -1.

    Tries the keyword as-is plus common ی/ك variants so we can slice the
    *original* characters for «جمله ایراددار» without rewriting the quote.
    """
    raw = text or ""
    if not raw or not keyword_norm:
        return -1
    variants = {
        keyword_norm,
        keyword_norm.replace("ی", "ي").replace("ک", "ك"),
        keyword_norm.replace("ي", "ی").replace("ك", "ک"),
    }
    lower = raw.lower()
    for v in variants:
        if not v:
            continue
        i = raw.find(v)
        if i >= 0:
            return i
        i = lower.find(v.lower())
        if i >= 0:
            return i
    return -1


def _map_norm_index_to_raw(raw: str, raw_norm: str, norm_idx: int) -> int:
    """Map an index in whitespace-collapsed normalized text back to raw text."""
    if not raw:
        return 0
    if not raw_norm or norm_idx <= 0:
        return 0
    # Walk both strings character-by-character under the same light rules.
    ri = 0
    ni = 0
    target = min(norm_idx, len(raw_norm))
    while ri < len(raw) and ni < target:
        ch = raw[ri]
        mapped = ch.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
        if mapped.isspace():
            # Collapsed whitespace in norm: skip all raw whitespace as one unit
            while ri < len(raw) and (
                raw[ri].isspace() or raw[ri] == "\u200c"
            ):
                ri += 1
            if ni < len(raw_norm) and raw_norm[ni].isspace():
                ni += 1
            continue
        # One-to-one letter after ی/ك fold + lower
        ri += 1
        ni += 1
    return min(ri, max(len(raw) - 1, 0))


def find_page_for_quote(
    documents: list[dict],
    *,
    filename: str | None,
    quote: str | None,
    keywords: list[str] | None = None,
    _norm_cache: dict[int, str] | None = None,
) -> int | None:
    """Locate quote/keywords inside the named file (or best match) and return page.

    When a concrete filename is known and that file has extracted text, never return
    None — fall back to page 1 so the UI never shows «نامشخص» for an attributed file.
    """
    if not documents:
        return None
    needle = (quote or "").strip()
    name = (filename or "").strip()
    norm_cache = _norm_cache if _norm_cache is not None else {}

    def _norm_text(d: dict) -> str:
        key = id(d)
        cached = norm_cache.get(key)
        if cached is None:
            cached = _normalize_fa_search(d.get("extracted_text") or "")
            norm_cache[key] = cached
        return cached

    def _match_doc(d: dict) -> bool:
        on = (d.get("original_name") or "").strip()
        if not name:
            return False
        return on == name or name in on or on in name

    named = [d for d in documents if _match_doc(d)]
    pool = named or list(documents)
    snippets: list[str] = []
    if needle:
        compact = re.sub(r"\s+", " ", needle)
        for n in (120, 80, 50, 40, 28, 18):
            if len(compact) >= 12:
                snippets.append(compact[:n])
        if len(compact) > 60:
            snippets.append(compact[20:90])
            snippets.append(compact[40:100])
        # Distinctive Latin / digit tokens from the quote (e.g. Claim Notice, 28)
        for tok in re.findall(r"[A-Za-z]{3,}(?:\s+[A-Za-z]{3,}){0,2}|\d{1,4}", compact):
            if len(tok) >= 3:
                snippets.append(tok)
    for k in keywords or []:
        if k and len(str(k).strip()) >= 3:
            snippets.append(str(k).strip())

    best_fallback: int | None = None
    for d in pool:
        text = d.get("extracted_text") or ""
        if not text.strip():
            continue
        if best_fallback is None:
            best_fallback = 1
        text_norm = _norm_text(d)
        for snip in snippets:
            sn = _normalize_fa_search(snip)
            if len(sn) < 4:
                continue
            i = text_norm.find(sn)
            if i >= 0:
                # Approximate original index from normalized position
                raw_i = min(int(i * (len(text) / max(len(text_norm), 1))), len(text) - 1)
                return estimate_page_at_index(text, max(0, raw_i))
        for k in keywords or []:
            kk = _normalize_fa_search(str(k or ""))
            if len(kk) < 3:
                continue
            i = text_norm.find(kk)
            if i >= 0:
                raw_i = min(int(i * (len(text) / max(len(text_norm), 1))), len(text) - 1)
                return estimate_page_at_index(text, max(0, raw_i))
        # Named file with text but no keyword hit → still attribute page 1
        if named and _match_doc(d):
            return 1

    # Filename known but empty OCR, or no filename: still prefer page 1 over «نامشخص»
    if name and named:
        return 1
    return best_fallback


def locate_document_excerpt(
    documents: list[dict],
    *,
    keywords: list[str] | None = None,
    prefer_categories: tuple[str, ...] = ("tender",),
    _norm_cache: dict[int, str] | None = None,
) -> tuple[str | None, str | None, int | None]:
    """
    Pick exactly ONE primary document + a short quote (and page) for report attribution.
    Scores by category preference, filename hints, then text keyword hits.
    """
    if not documents:
        return None, None, None

    norm_cache = _norm_cache if _norm_cache is not None else {}

    def _cat(d: dict) -> str:
        c = d.get("category")
        return c.value if hasattr(c, "value") else str(c or "")

    def _norm_doc(d: dict) -> str:
        key = id(d)
        cached = norm_cache.get(key)
        if cached is None:
            cached = _normalize_fa_search(d.get("extracted_text") or "")
            norm_cache[key] = cached
        return cached

    keys = [_normalize_fa_search(k) for k in (keywords or []) if k and len(str(k).strip()) >= 2]
    keys = [k for k in keys if k]
    # Filename cues that usually hold scope / particular conditions content
    name_boost = [
        "شرح",
        "محدوده",
        "خصوص",
        "اختصاص",
        "scope",
        "sow",
        "particular",
        "spec",
        "شرایط",
        "الزام",
        "فنی",
        "ایمنی",
        "پیمان",
        "contract",
        "tender",
        "claim",
        "ادعا",
    ]

    scored: list[tuple[int, int, dict, int, str]] = []
    for d in documents:
        name = (d.get("original_name") or "").strip()
        text = d.get("extracted_text") or ""
        cat = _cat(d)
        score = 0
        if cat in prefer_categories:
            score += 40 - prefer_categories.index(cat) * 8
        name_l = _normalize_fa_search(name)
        for hint in name_boost:
            if _normalize_fa_search(hint) in name_l:
                score += 25
                break
        for hint in keys:
            if hint in name_l:
                score += 35
        hit_idx = -1
        text_l = _norm_doc(d)
        for k in keys:
            # Prefer a hit in the raw extracted text so the quote slice is exact.
            raw_hit = _raw_keyword_index(text, k)
            if raw_hit >= 0:
                hit_idx = raw_hit
                score += 50
                break
            i = text_l.find(k)
            if i >= 0:
                hit_idx = _map_norm_index_to_raw(text, text_l, i)
                score += 50
                break
        if not text.strip():
            score -= 20
        elif has_usable_text(text):
            score += 10
            # Prefer documents whose Persian is already readable (not visual-RTL garbage)
            from app.services.extractor import _fa_token_score, _looks_visually_reversed

            sample = text[:1200]
            if _looks_visually_reversed(sample):
                score -= 25
            else:
                score += min(20, _fa_token_score(sample))
        scored.append((score, hit_idx, d, hit_idx, name))

    if not scored:
        return None, None, None
    scored.sort(key=lambda row: (-row[0], row[3] if row[3] >= 0 else 10**9))
    best_score, _, best, hit_idx, name = scored[0]
    if best_score < 0 and not name:
        return None, None, None

    text = best.get("extracted_text") or ""
    if hit_idx >= 0 and text:
        chunk = sentence_around_index(text, hit_idx, max_len=500)
        if chunk:
            return name or None, chunk, estimate_page_at_index(text, hit_idx)
        start = max(0, hit_idx - 40)
        end = min(len(text), hit_idx + 220)
        chunk = text[start:end].strip()
        return name or None, verbatim_document_excerpt(chunk, max_len=500), estimate_page_at_index(text, hit_idx)

    sentence = _first_sentence(text) if text.strip() else None
    # Always give a page when we attribute a file that has any text
    page = estimate_page_at_index(text, 0) if text.strip() else None
    return name or None, sentence, page


def _first_sentence(text: str, max_len: int = 500) -> str | None:
    from app.services.extractor import _fa_token_score, clean_display_excerpt

    cleaned = strip_extraction_chrome(text or "")
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    if not lines:
        return clean_display_excerpt(cleaned, max_len=max_len)
    # Prefer a substantial, readable body line (highest Persian token score).
    ranked: list[tuple[int, str]] = []
    for line in lines:
        if len(line) < 20 or line.lower().startswith("page "):
            continue
        parts = re.split(r"(?<=[.!?؟。])\s+", line)
        candidate = next((p.strip() for p in parts if len(p.strip()) >= 20), line)
        ranked.append((_fa_token_score(candidate), candidate))
    if ranked:
        ranked.sort(key=lambda row: (-row[0], -len(row[1])))
        return clean_display_excerpt(ranked[0][1], max_len=max_len)
    return clean_display_excerpt(lines[0], max_len=max_len)

def _doc_names(docs: list[dict], *, limit: int = 8) -> list[str]:
    names: list[str] = []
    for d in docs:
        n = (d.get("original_name") or "").strip()
        if n and n not in names:
            names.append(n)
        if len(names) >= limit:
            break
    return names


def _category_label(cat: DocumentCategory | str, lang: LanguageCode) -> str:
    key = cat.value if isinstance(cat, DocumentCategory) else str(cat)
    labels = {
        "tender": {
            LanguageCode.FA: "اسناد مناقصه",
            LanguageCode.EN: "tender documents",
            LanguageCode.DE: "Ausschreibungsunterlagen",
            LanguageCode.FR: "documents d'appel d'offres",
        },
        "drawing": {
            LanguageCode.FA: "نقشه‌ها",
            LanguageCode.EN: "drawings",
            LanguageCode.DE: "Pläne",
            LanguageCode.FR: "plans",
        },
        "schedule": {
            LanguageCode.FA: "برنامه زمان‌بندی",
            LanguageCode.EN: "schedule",
            LanguageCode.DE: "Terminplan",
            LanguageCode.FR: "planning",
        },
        "standard": {
            LanguageCode.FA: "استانداردها",
            LanguageCode.EN: "standards",
            LanguageCode.DE: "Standards",
            LanguageCode.FR: "normes",
        },
    }
    return labels.get(key, {}).get(lang) or key


def enrich_findings_document_sources(
    findings: list[RiskFinding],
    documents: list[dict],
    *,
    lang: LanguageCode,
) -> list[RiskFinding]:
    """Ensure every risk finding names the file(s) the user should open or upload."""
    by_cat: dict[str, list[dict]] = {"tender": [], "drawing": [], "schedule": [], "standard": []}
    for d in documents:
        c = d.get("category")
        key = c.value if hasattr(c, "value") else str(c or "")
        if key in by_cat:
            by_cat[key].append(d)

    all_names = _doc_names(documents, limit=12)
    norm_cache: dict[int, str] = {}

    for f in findings:
        if f.finding_category == "limitation":
            if not f.source_document_name and f.evidence:
                first = re.split(r"[،,;|/]+", f.evidence)[0].strip()
                f.source_document_name = (first or f.evidence)[:512]
            continue

        # Collapse accidental multi-file labels to a single filename
        if f.source_document_name and ("،" in f.source_document_name or "," in f.source_document_name):
            if "بارگذاری نشده" not in f.source_document_name and "uploaded" not in f.source_document_name.lower():
                parts = re.split(r"\s*[،,]\s*", f.source_document_name)
                parts = [p.strip() for p in parts if p.strip()]
                if parts:
                    f.source_document_name = parts[0]

        # Experience + risk cards both need a concrete file name and page
        needs_file = not f.source_document_name or "،" in (f.source_document_name or "")
        if f.finding_category == "experience":
            hints = [
                w
                for w in re.findall(
                    r"[\w\u0600-\u06FFA-Za-z]{3,}",
                    f"{f.title or ''} {f.description or ''} {f.source_excerpt or ''}",
                )
                if w.lower()
                not in {
                    "iran",
                    "ایران",
                    "پروژه",
                    "project",
                    "تجربه",
                    "experience",
                    "این",
                    "الگو",
                    "قبلی",
                    "مبتنی",
                    "معمولا",
                    "the",
                    "and",
                    "for",
                }
            ][:16]
            # Prefer title tokens (e.g. Claim Notice) for locating the real PDF sentence
            title_hints = [
                w
                for w in re.findall(r"[\w\u0600-\u06FFA-Za-z]{3,}", f.title or "")
                if len(w) >= 3
            ][:10]
            search_hints = title_hints + [h for h in hints if h not in title_hints]
            name, excerpt, page = locate_document_excerpt(
                documents,
                keywords=search_hints or hints,
                prefer_categories=("tender",),
                _norm_cache=norm_cache,
            )
            if needs_file and name:
                f.source_document_name = name
            elif not f.source_document_name and name:
                f.source_document_name = name
            # Prefer a real document sentence over the advisory experience blurb
            if excerpt and (
                not f.source_excerpt
                or "validation_status" in (f.source_excerpt or "")
                or "پروژه‌های قبلی" in (f.source_excerpt or "")
                or "previous projects" in (f.source_excerpt or "").lower()
                or len(f.source_excerpt or "") > 400
            ):
                # Only replace when excerpt looks like document text (or we had no quote)
                if excerpt != f.source_excerpt:
                    f.source_excerpt = excerpt
            if f.source_page is None and page is not None:
                f.source_page = page
            if f.source_page is None:
                f.source_page = find_page_for_quote(
                    documents,
                    filename=f.source_document_name or name,
                    quote=f.source_excerpt or excerpt,
                    keywords=search_hints or hints,
                    _norm_cache=norm_cache,
                )
            continue

        if f.finding_category and f.finding_category not in {"risk", "experience"}:
            continue

        code = (f.code or "").upper()
        # Engineered standards-gap findings already carry a clear explanation;
        # do not invent a fake tender quote from a code list.
        if code.startswith(("STD-TOPIC-", "STD-CITE-", "STD-CONTENT-")):
            continue

        if (
            f.source_document_name
            and f.source_excerpt
            and f.source_page is not None
            and "،" not in (f.source_document_name or "")
        ):
            continue

        title = (f.title or "").lower()
        desc = (f.description or "").lower()
        blob = f"{title} {desc} {f.evidence or ''}".lower()

        missing_cat: DocumentCategory | None = None
        if f.finding_category == "risk":
            if "standard" in blob or "استاندارد" in blob or code.startswith("STD-001"):
                if not by_cat["standard"]:
                    missing_cat = DocumentCategory.STANDARD
            elif "schedule" in blob or "زمان‌بند" in blob or "termin" in blob or code.startswith("SCHED"):
                if not by_cat["schedule"]:
                    missing_cat = DocumentCategory.SCHEDULE
            elif "drawing" in blob or "نقشه" in blob or code.startswith("DRAW"):
                if not by_cat["drawing"]:
                    missing_cat = DocumentCategory.DRAWING

        if missing_cat is not None:
            cat_l = _category_label(missing_cat, lang)
            f.source_document_name = {
                LanguageCode.FA: f"— (فایل «{cat_l}» بارگذاری نشده)",
                LanguageCode.EN: f"— (no «{cat_l}» file uploaded)",
                LanguageCode.DE: f"— (keine «{cat_l}»-Datei)",
                LanguageCode.FR: f"— (aucun fichier «{cat_l}»)",
            }[lang][:512]
            if not f.source_excerpt:
                present = "، ".join(all_names[:6]) if all_names else "—"
                f.source_excerpt = {
                    LanguageCode.FA: f"در بین اسناد پروژه، هیچ فایلی در دسته «{cat_l}» نیست. اسناد فعلی پروژه: {present}",
                    LanguageCode.EN: f"No project file in «{cat_l}». Current files: {present}",
                    LanguageCode.DE: f"Keine Datei in «{cat_l}». Vorhanden: {present}",
                    LanguageCode.FR: f"Aucun fichier «{cat_l}». Fichiers actuels: {present}",
                }[lang]
            f.source_page = None
            continue

        # Content findings → attach exactly one best-matching file
        hints = [
            w
            for w in re.findall(r"[\w\u0600-\u06FF]{3,}", f"{f.title or ''} {f.description or ''}")
            if w.lower() not in {"iran", "ایران", "پروژه", "project"}
        ][:10]
        prefer = ("tender",)
        if by_cat["schedule"] and ("schedule" in blob or "زمان" in blob):
            prefer = ("schedule", "tender")
        elif by_cat["drawing"] and ("drawing" in blob or "نقشه" in blob):
            prefer = ("drawing", "tender")
        elif by_cat["standard"] and ("standard" in blob or "استاندارد" in blob):
            prefer = ("standard", "tender")

        name, excerpt, page = locate_document_excerpt(
            documents,
            keywords=hints,
            prefer_categories=prefer,
            _norm_cache=norm_cache,
        )
        if not f.source_document_name or "،" in f.source_document_name or "," in f.source_document_name:
            f.source_document_name = name
        if not f.source_excerpt and excerpt:
            f.source_excerpt = excerpt
        if f.source_page is None:
            f.source_page = page or find_page_for_quote(
                documents,
                filename=f.source_document_name,
                quote=f.source_excerpt or excerpt,
                keywords=hints,
                _norm_cache=norm_cache,
            )

    return findings


def _lang(map_: dict[LanguageCode, str], lang: LanguageCode) -> str:
    return map_.get(lang) or map_.get(LanguageCode.EN) or next(iter(map_.values()))


def _impact_label(level: str | None, lang: LanguageCode) -> str | None:
    """Localize high/medium/low impact tags so findings never mix EN into FA/DE UI."""
    if not level:
        return None
    key = str(level).strip().lower()
    labels = {
        "high": {
            LanguageCode.FA: "بالا",
            LanguageCode.EN: "high",
            LanguageCode.DE: "hoch",
            LanguageCode.FR: "élevé",
        },
        "medium": {
            LanguageCode.FA: "متوسط",
            LanguageCode.EN: "medium",
            LanguageCode.DE: "mittel",
            LanguageCode.FR: "moyen",
        },
        "low": {
            LanguageCode.FA: "پایین",
            LanguageCode.EN: "low",
            LanguageCode.DE: "niedrig",
            LanguageCode.FR: "faible",
        },
    }
    bucket = labels.get(key)
    if not bucket:
        return level
    return _lang(bucket, lang)


# ---------------------------------------------------------------------------
# Risk composition model (likelihood × impact)
#
# Three UI fields are related — not independent — as follows:
#
#   likelihood  = how strongly the triggered pattern / detection prior ranks
#                 (rule severity, or a 0–100 detection score mapped to a band)
#   impact      = consequence magnitude = max(financial_impact, schedule_impact)
#   risk_score  = round(100 × L × I / 9)   with L,I ∈ {1,2,3} for low/med/high
#   severity    = HIGH if score≥70; MEDIUM if score≥40; else LOW
#   estimated_impact = financial (cost) axis only — shown separately so readers
#                      see consequence size without confusing it with priority
#
# Example: likelihood=high (3), financial=low (1), schedule=medium (2)
#   → I=max(1,2)=2 → score=round(100*3*2/9)=67 → severity=MEDIUM
#   → estimated_impact displays "low" (financial)
# ---------------------------------------------------------------------------

_LEVEL_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3}
_RANK_ALIASES: dict[str, str] = {
    "بالا": "high",
    "متوسط": "medium",
    "پایین": "low",
    "hoch": "high",
    "mittel": "medium",
    "niedrig": "low",
    "élevé": "high",
    "eleve": "high",
    "moyen": "medium",
    "faible": "low",
}


def _normalize_level_key(level: object | None) -> str | None:
    if level is None:
        return None
    if isinstance(level, RiskSeverity):
        return level.value
    if isinstance(level, (int, float)):
        score = int(round(float(level)))
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        return "low"
    key = str(level).strip().lower()
    if key in _LEVEL_RANK:
        return key
    return _RANK_ALIASES.get(key) or _RANK_ALIASES.get(str(level).strip())


def _level_rank(level: object | None, *, default: int = 2) -> int:
    key = _normalize_level_key(level)
    if key is None:
        return default
    return _LEVEL_RANK.get(key, default)


def compose_finding_risk(
    *,
    likelihood: RiskSeverity | str | int | float | None,
    financial_impact: str | None = None,
    schedule_impact: str | None = None,
) -> tuple[int, RiskSeverity, str | None]:
    """Return (risk_score 0–100, severity badge, estimated_impact level key).

    See module comment above for the likelihood × impact formula.
    """
    L = _level_rank(likelihood, default=2)
    fin_r = _level_rank(financial_impact, default=0) if financial_impact else 0
    sch_r = _level_rank(schedule_impact, default=0) if schedule_impact else 0
    if fin_r or sch_r:
        I = max(fin_r, sch_r)
    else:
        I = 2
    score = int(round(100 * L * I / 9))
    score = max(0, min(100, score))
    severity = _severity_from_score(score)
    impact_key = _normalize_level_key(financial_impact) or _normalize_level_key(schedule_impact)
    return score, severity, impact_key


def _severity_from_score(score: int) -> RiskSeverity:
    if score >= 70:
        return RiskSeverity.HIGH
    if score >= 40:
        return RiskSeverity.MEDIUM
    return RiskSeverity.LOW


def _with_score(finding: RiskFinding, score: int | None) -> RiskFinding:
    if score is None:
        return finding
    finding.risk_score = max(0, min(100, score))
    if finding.finding_category == "risk":
        finding.severity = _severity_from_score(finding.risk_score)
    return finding


def apply_composed_risk(
    finding: RiskFinding,
    *,
    likelihood: RiskSeverity | str | int | float | None,
    financial_impact: str | None,
    schedule_impact: str | None,
    lang: LanguageCode,
) -> RiskFinding:
    """Set score / severity / estimated_impact from the shared composition model."""
    score, severity, impact_key = compose_finding_risk(
        likelihood=likelihood,
        financial_impact=financial_impact,
        schedule_impact=schedule_impact,
    )
    finding.risk_score = score
    if finding.finding_category == "risk":
        finding.severity = severity
    finding.financial_impact = _impact_label(financial_impact, lang) if financial_impact else finding.financial_impact
    finding.schedule_impact = _impact_label(schedule_impact, lang) if schedule_impact else finding.schedule_impact
    finding.estimated_impact = _impact_label(impact_key, lang) if impact_key else finding.estimated_impact
    return finding


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def _extraction_stats(documents: list[dict]) -> dict:
    total = len(documents)

    def _cat(d: dict) -> str:
        c = d.get("category")
        return c.value if isinstance(c, DocumentCategory) else str(c)

    # Drawings are often CAD/vector with no text — never use them to block analysis.
    text_docs = [d for d in documents if _cat(d) != DocumentCategory.DRAWING.value]
    drawing_docs = [d for d in documents if _cat(d) == DocumentCategory.DRAWING.value]

    readable_text = [d for d in text_docs if has_usable_text(d.get("extracted_text") or "")]
    failed_text = [d for d in text_docs if not has_usable_text(d.get("extracted_text") or "")]
    gate_rate = (len(readable_text) / len(text_docs)) if text_docs else 0.0

    failed_all = [d for d in documents if not has_usable_text(d.get("extracted_text") or "")]
    readable_all = [d for d in documents if has_usable_text(d.get("extracted_text") or "")]
    overall = (len(readable_all) / total) if total else 0.0

    # Same criterion as STD-SEED-005 / OCR empty-text limitations (drawings excluded
    # unless they have an explicit low confidence score).
    limitation_docs = [d for d in documents if document_has_extraction_limitation(d)]

    return {
        "total": total,
        "text_doc_count": len(text_docs),
        "drawing_count": len(drawing_docs),
        "readable_count": len(readable_text),
        "failed_count": len(failed_text),
        "failed_names": [d.get("original_name") or "unnamed" for d in failed_text],
        "readable_names": [d.get("original_name") or "unnamed" for d in readable_text],
        "limitation_count": len(limitation_docs),
        "limitation_names": [d.get("original_name") or "unnamed" for d in limitation_docs],
        "low_confidence_count": sum(1 for d in documents if has_low_extraction_confidence(d)),
        "success_rate": overall,
        "gate_rate": gate_rate,
    }


def _extraction_readiness_clause(stats: dict, readiness_pct: int, lang: LanguageCode) -> str:
    """Two clear numbers: how many files were text-processed, and success among those."""
    total = int(stats.get("total") or 0)
    text_n = int(stats.get("text_doc_count") or 0)
    ok_n = int(stats.get("readable_count") or 0)
    drawings = int(stats.get("drawing_count") or 0)
    if lang == LanguageCode.FA:
        if text_n <= 0:
            return (
                f"از {total} فایل، سند متنی برای استخراج وجود نداشت"
                + (f" ({drawings} نقشه جدا از محاسبهٔ متن)" if drawings else "")
                + "."
            )
        return (
            f"{text_n} از {total} فایل برای استخراج متن پردازش شد؛ "
            f"از این تعداد {readiness_pct}٪ با موفقیت استخراج شدند "
            f"({ok_n}/{text_n})"
            + (f"؛ {drawings} نقشه در محاسبهٔ استخراج متن لحاظ نشد" if drawings else "")
            + "."
        )
    if lang == LanguageCode.DE:
        if text_n <= 0:
            return f"Von {total} Dateien keine Textdokumente zur Extraktion."
        return (
            f"{text_n} von {total} Dateien für Textextraktion verarbeitet; "
            f"davon {readiness_pct}% erfolgreich ({ok_n}/{text_n})"
            + (f"; {drawings} Pläne nicht in der Textquote" if drawings else "")
            + "."
        )
    if lang == LanguageCode.FR:
        if text_n <= 0:
            return f"Sur {total} fichiers, aucun document texte à extraire."
        return (
            f"{text_n} fichiers sur {total} traités pour l'extraction texte ; "
            f"dont {readiness_pct}% réussis ({ok_n}/{text_n})"
            + (f" ; {drawings} plans exclus du taux texte" if drawings else "")
            + "."
        )
    # EN default
    if text_n <= 0:
        return (
            f"Of {total} files, no text documents were available for extraction"
            + (f" ({drawings} drawings excluded from text rate)" if drawings else "")
            + "."
        )
    return (
        f"{text_n} of {total} files were processed for text extraction; "
        f"of those, {readiness_pct}% extracted successfully ({ok_n}/{text_n})"
        + (f"; {drawings} drawings excluded from the text rate" if drawings else "")
        + "."
    )


# Subject-matter topics for semantic coverage (NOT standard title strings).
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "fire": ["حریق", "آتش", "اطفا", "خروج اضطراری", "fire", "sprinkler", "evacuation", "Brandschutz", "A-FIRE"],
    "electrical": ["برق", "الکتریکال", "تابلو", "کابل", "روشنایی", "electrical", "voltage", "panel", "Elektro", "ELEC", "lighting"],
    "mechanical": ["مکانیک", "تهویه", "HVAC", "چیلر", "دیگ", "mechanical", "ventilation", "heating", "MECH", "duct"],
    "plumbing": ["لوله", "فاضلاب", "آبرسانی", "بهداشتی", "plumbing", "sanitary", "drainage", "آبگرم", "PLUMB", "sanitär"],
    "structure_concrete": ["بتن", "آرمه", "مقاومت فشاری", "concrete", "rebar", "cover", "Beton", "S-CONC"],
    "structure_steel": ["فولاد", "سازه فولادی", "اتصالات", "steel", "welding", "Stahlbau", "S-STEEL", "beam", "column"],
    "foundation": ["پی", "فونداسیون", "ژئوتکنیک", "foundation", "pile", "soil", "Gründung", "S-FND"],
    "loads": ["بار", "زلزله", "باد", "بار زنده", "seismic", "load", "dead load", "Last"],
    "energy": ["انرژی", "عایق حرارتی", "مصرف انرژی", "energy", "insulation", "U-value"],
    "gas": ["گاز", "لوله گاز", "gas piping", "Gasleitung"],
    "elevator": ["آسانسور", "پله برقی", "elevator", "lift", "escalator"],
    "safety_site": ["ایمنی کارگاه", "HSE", "حفاظت کار", "safety", "PPE", "Arbeitsschutz"],
    "acoustic": ["صدا", "عایق صوتی", "acoustic", "Schallschutz"],
    "boq_building": ["فهرست بها", "ابنیه", "متره", "ردیف", "برآورد", "quantity", "unit price"],
    "boq_elec": ["فهرست بها", "تأسیسات برقی", "ردیف برقی"],
    "boq_mech": ["فهرست بها", "تأسیسات مکانیکی", "ردیف مکانیکی"],
    "contract_general": ["شرایط عمومی", "کارفرما", "پیمانکار", "تعهدات", "VOB", "CCDC", "FIDIC", "clause"],
    "payment": ["پرداخت", "صورت وضعیت", "پیش پرداخت", "retention", "payment", "holdback"],
    "claims": ["ادعا", "تغییر مقادیر", "دستور کار", "claim", "variation", "change order", "Nachtrag"],
    "schedule": ["برنامه زمان", "مایلستون", "مدت پیمان", "schedule", "programme", "milestone", "completion"],
    "scope": ["شرح کار", "محدوده کار", "scope", "Leistungsbeschreibung", "ARCH", "A-WALL", "A-DOOR", "floor", "level", "plan"],
}


def _topics_for_standard(code: str, title: str, sclass: str) -> list[str]:
    """Map a catalog standard to subject topics (semantic), not its literal name."""
    c = (code or "").upper()
    t = (title or "").lower()
    blob = f"{c} {t}".lower()
    topics: list[str] = []

    if sclass == "contractual" or "GENERAL_CONDITIONS" in c or "VOB" in c or "CCDC" in c or "FIDIC" in c:
        topics.extend(["contract_general", "payment", "claims"])
    if "NBR_03" in c or "حریق" in t or "fire" in t:
        topics.append("fire")
    if "NBR_13" in c or "برقی" in t or "electrical" in t or "bargh" in blob or "elec" in blob:
        topics.append("electrical")
    if "NBR_14" in c or "مکانیک" in t or "mechanic" in blob or "hvac" in blob:
        topics.append("mechanical")
    if "NBR_16" in c or "بهداشت" in t or "plumbing" in t:
        topics.append("plumbing")
    if "NBR_09" in c or "بتن" in t:
        topics.append("structure_concrete")
    if "NBR_10" in c or "فولاد" in t:
        topics.append("structure_steel")
    if "NBR_07" in c or "پی" in t:
        topics.append("foundation")
    if "NBR_06" in c or "بار" in t:
        topics.append("loads")
    if "NBR_19" in c or "انرژی" in t:
        topics.append("energy")
    if "NBR_17" in c or "گاز" in t:
        topics.append("gas")
    if "NBR_15" in c or "آسانسور" in t:
        topics.append("elevator")
    if "NBR_12" in c or "HSE" in c or "ایمنی" in t or "safety" in blob:
        topics.append("safety_site")
    if "NBR_18" in c or "صدا" in t:
        topics.append("acoustic")
    if (
        "FEHREST_ABNIEH" in c
        or "abnieh" in blob
        or ("فهرست" in t and "ابنیه" in t)
        or "ابنیه" in t
    ):
        topics.append("boq_building")
    if "FEHREST_TAASISAT_BARGH" in c or ("فهرست" in t and "برق" in t):
        topics.append("boq_elec")
    if "FEHREST_TAASISAT_MECHANIC" in c or ("فهرست" in t and "مکانیک" in t) or (
        "fehrest" in blob and "mechanic" in blob
    ):
        topics.append("boq_mech")
    if ("FEHREST" in c or "فهرست" in t or "fehrest" in blob) and not any(
        x in topics for x in ("boq_building", "boq_elec", "boq_mech")
    ):
        topics.append("boq_building")
    if "DIN_1045" in c:
        topics.append("structure_concrete")
    if "NBC" in c:
        topics.extend(["structure_concrete", "fire", "loads"])
    if not topics:
        # Generic technical: look for any engineering substance markers
        topics.append("scope")
    return list(dict.fromkeys(topics))


def _corpus_covers_topic(corpus: str, topic: str) -> bool:
    kws = _TOPIC_KEYWORDS.get(topic) or []
    return bool(kws) and _contains_any(corpus, kws)


def _citation_tokens_for_standard(code: str, title: str, original_name: str | None = None) -> list[str]:
    """Distinctive tokens used to detect whether tender docs cite a selected standard."""
    raw = f"{code} {title} {original_name or ''}"
    parts: list[str] = []
    for tok in re.findall(r"[A-Za-z]{3,}|\d{3,}[\w.-]*|[\u0600-\u06FF]{3,}", raw):
        t = tok.strip("._-")
        if len(t) < 3:
            continue
        low = t.lower()
        if low in {"pdf", "docx", "the", "and", "for", "std", "nbr", "iran"}:
            continue
        parts.append(t)
    # Prefer longer / more specific tokens first
    parts.sort(key=lambda x: (-len(x), x.lower()))
    out: list[str] = []
    for p in parts:
        if p.lower() not in {x.lower() for x in out}:
            out.append(p)
        if len(out) >= 8:
            break
    return out


def _standard_content_markers(standard_text: str, *, limit: int = 12) -> list[str]:
    """Pick distinctive content markers from extracted catalog standard text."""
    if not (standard_text or "").strip():
        return []
    text = _normalize_fa_search(standard_text[:20_000])
    cands = re.findall(r"[a-zA-Z\u0600-\u06FF]{5,}", text)
    stop = {
        "project",
        "standard",
        "استاندارد",
        "ماده",
        "بند",
        "صفحه",
        "جدول",
        "chapter",
        "section",
        "iran",
        "ایران",
        "shall",
        "must",
        "should",
        "پیمانکار",
        "کارفرما",
    }
    out: list[str] = []
    seen: set[str] = set()
    for w in cands:
        key = w.lower()
        if key in stop or key in seen:
            continue
        seen.add(key)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _analyze_selected_standards_semantic(
    *,
    lang: LanguageCode,
    selected_standards: list[dict],
    tender_text: str,
    standard_text: str,
    drawing_text: str = "",
    caveat: str | None,
) -> list[RiskFinding]:
    """
    Semantic topic coverage — not literal standard-name matching.
    Also checks citation of selected standards and content overlap with tender docs.
    Unverifiable standards → consolidated findings.
    """
    if not selected_standards:
        return []

    findings: list[RiskFinding] = []
    technical_corpus = f"{tender_text}\n{standard_text}\n{drawing_text}"
    contract_corpus = tender_text
    tender_norm = _normalize_fa_search(tender_text)
    unverifiable: list[str] = []
    uncited: list[str] = []
    weak_content: list[str] = []

    for item in selected_standards:
        code = item.get("code") or ""
        title = item.get("title") or code
        sclass = item.get("standard_class") or "technical"
        original_name = item.get("original_name") or ""
        item_text = (item.get("extracted_text") or "").strip()
        std = get_standard(code)
        if std:
            title = std.title_for(lang.value if hasattr(lang, "value") else str(lang))
        topics = _topics_for_standard(code, title, sclass)
        corpus = contract_corpus if sclass == "contractual" else technical_corpus
        covered = any(_corpus_covers_topic(corpus, topic) for topic in topics)
        if not covered:
            unverifiable.append(title)

        cite_tokens = _citation_tokens_for_standard(code, title, original_name)
        cited = False
        if tender_norm and cite_tokens:
            for tok in cite_tokens[:6]:
                if _normalize_fa_search(tok) in tender_norm:
                    cited = True
                    break
        if tender_norm and cite_tokens and not cited:
            uncited.append(title)

        # When we have catalog PDF text, require at least light content overlap with tender.
        markers = _standard_content_markers(item_text) if item_text else []
        if markers and tender_norm:
            hits = sum(1 for m in markers if _normalize_fa_search(m) in tender_norm)
            if hits < 2:
                weak_content.append(title)

    if unverifiable:
        preview = "؛ ".join(unverifiable[:12])
        more = f" (+{len(unverifiable) - 12})" if len(unverifiable) > 12 else ""
        findings.append(
            apply_composed_risk(
                RiskFinding(
                    code="STD-TOPIC-GAP-001",
                    category="compliance",
                    severity=RiskSeverity.MEDIUM,
                    finding_category="risk",
                    title={
                        LanguageCode.FA: "پوشش موضوعی استانداردهای انتخاب‌شده در اسناد ناقص است",
                        LanguageCode.EN: "Selected standards’ subject matter is not covered in documents",
                        LanguageCode.DE: "Themen der gewählten Standards in Unterlagen nicht abgedeckt",
                        LanguageCode.FR: "Sujets des normes sélectionnées non couverts dans les documents",
                    }[lang],
                    description={
                        LanguageCode.FA: (
                            f"{len(unverifiable)} استاندارد انتخاب‌شده از نظر موضوعی در متن قابل‌خواندن اسناد "
                            f"قابل راستی‌آزمایی نبودند (نه صرفاً به‌خاطر نبودن نام استاندارد): {preview}{more}"
                        ),
                        LanguageCode.EN: (
                            f"{len(unverifiable)} selected standards could not be verified by subject matter "
                            f"in readable document text (not merely missing the standard’s name): {preview}{more}"
                        ),
                        LanguageCode.DE: (
                            f"{len(unverifiable)} gewählte Standards thematisch nicht verifizierbar: {preview}{more}"
                        ),
                        LanguageCode.FR: (
                            f"{len(unverifiable)} normes non vérifiables par sujet: {preview}{more}"
                        ),
                    }[lang],
                    recommendation={
                        LanguageCode.FA: (
                            "در مشخصات فنی/شرایط خصوصی، برای هر حوزهٔ بدون پوشش (مثلاً حریق، برق، بتن) "
                            "یک بخش اختصاصی با الزامات قابل‌اندازه‌گیری اضافه کنید؛ سپس همان استاندارد مرتبط را ارجاع دهید."
                        ),
                        LanguageCode.EN: (
                            "Add dedicated measurable sections in specs/particular conditions for each uncovered "
                            "domain (e.g. fire, electrical, concrete), then cite the related standard."
                        ),
                        LanguageCode.DE: (
                            "Für jedes ungedeckte Thema (Brandschutz, Elektro, Beton) messbare Abschnitte "
                            "in Specs/besondere Bedingungen ergänzen und den Standard zitieren."
                        ),
                        LanguageCode.FR: (
                            "Ajouter des sections mesurables pour chaque domaine non couvert, puis citer la norme."
                        ),
                    }[lang],
                    evidence=preview,
                    source_excerpt={
                        LanguageCode.FA: (
                            "در متن اسناد مناقصه، بخش موضوعی قابل‌راستی‌آزمایی برای این استانداردها "
                            "پیدا نشد. فهرست کد/عنوان استانداردها در بخش شواهد آمده است."
                        ),
                        LanguageCode.EN: (
                            "No verifiable subject-matter section for these standards was found in tender text. "
                            "See evidence for the standard list."
                        ),
                        LanguageCode.DE: (
                            "Kein thematisch prüfbarer Abschnitt zu diesen Standards im Ausschreibungstext. "
                            "Liste siehe Evidenz."
                        ),
                        LanguageCode.FR: (
                            "Aucune section thématique vérifiable pour ces normes dans l'AO. "
                            "Voir la liste dans les preuves."
                        ),
                    }[lang],
                    source_document_name=None,
                    source_page=None,
                    cause_effect_chain=[
                        {
                            LanguageCode.FA: "بخش موضوعی استاندارد در اسناد نیست",
                            LanguageCode.EN: "Standard subject section missing in docs",
                            LanguageCode.DE: "Themenabschnitt fehlt",
                            LanguageCode.FR: "Section thématique absente",
                        }[lang],
                        {
                            LanguageCode.FA: "پیشنهاددهندگان الزامات را متفاوت تفسیر می‌کنند",
                            LanguageCode.EN: "Bidders interpret requirements differently",
                            LanguageCode.DE: "Bieter interpretieren unterschiedlich",
                            LanguageCode.FR: "Interprétations divergentes des soumissionnaires",
                        }[lang],
                        {
                            LanguageCode.FA: "اختلاف حین اجرا / ادعای تغییر",
                            LanguageCode.EN: "Dispute / variation claim during execution",
                            LanguageCode.DE: "Streit / Nachtrag in der Ausführung",
                            LanguageCode.FR: "Litige / avenant en exécution",
                        }[lang],
                        {
                            LanguageCode.FA: "تأخیر و افزایش هزینه برای کارفرما",
                            LanguageCode.EN: "Delay and cost growth for the employer",
                            LanguageCode.DE: "Verzug und Mehrkosten für Auftraggeber",
                            LanguageCode.FR: "Retard et surcoût pour le maître d'ouvrage",
                        }[lang],
                    ],
                    data_completeness_caveat=caveat,
                ),
                likelihood=RiskSeverity.MEDIUM,
                financial_impact="medium",
                schedule_impact="medium",
                lang=lang,
            )
        )

    if uncited:
        preview = "؛ ".join(uncited[:12])
        more = f" (+{len(uncited) - 12})" if len(uncited) > 12 else ""
        findings.append(
            apply_composed_risk(
                RiskFinding(
                    code="STD-CITE-001",
                    category="compliance",
                    severity=RiskSeverity.HIGH,
                    finding_category="risk",
                    title={
                        LanguageCode.FA: "استانداردهای انتخاب‌شده در اسناد مناقصه ارجاع نشده‌اند",
                        LanguageCode.EN: "Selected standards are not cited in tender documents",
                        LanguageCode.DE: "Gewählte Standards in Ausschreibungsunterlagen nicht zitiert",
                        LanguageCode.FR: "Normes sélectionnées non citées dans les documents d'AO",
                    }[lang],
                    description={
                        LanguageCode.FA: (
                            f"{len(uncited)} استاندارد انتخاب‌شده در متن اسناد مناقصه با نام/کد پیدا نشد: "
                            f"{preview}{more}"
                        ),
                        LanguageCode.EN: (
                            f"{len(uncited)} selected standards were not found by name/code in tender text: "
                            f"{preview}{more}"
                        ),
                        LanguageCode.DE: (
                            f"{len(uncited)} Standards nicht per Name/Code in Ausschreibungstext gefunden: "
                            f"{preview}{more}"
                        ),
                        LanguageCode.FR: (
                            f"{len(uncited)} normes introuvables par nom/code dans l'AO: {preview}{more}"
                        ),
                    }[lang],
                    recommendation={
                        LanguageCode.FA: (
                            "در شرایط خصوصی/مشخصات فنی، هر استاندارد انتخاب‌شده را صریح ارجاع دهید "
                            "(کد یا عنوان کامل) تا مبنای الزام‌آور مناقصه باشد."
                        ),
                        LanguageCode.EN: (
                            "Explicitly cite each selected standard (code or full title) in particular "
                            "conditions / technical specs so it is tender-binding."
                        ),
                        LanguageCode.DE: (
                            "Jeden gewählten Standard in besonderen Bedingungen / Specs ausdrücklich zitieren."
                        ),
                        LanguageCode.FR: (
                            "Citer explicitement chaque norme sélectionnée dans les conditions particulières / CCTP."
                        ),
                    }[lang],
                    evidence=preview,
                    source_excerpt={
                        LanguageCode.FA: (
                            "نام یا کد این استانداردهای انتخاب‌شده در متن اسناد مناقصه دیده نشد. "
                            "فهرست آن‌ها در شواهد آمده است — این یک جملهٔ قرارداد نیست."
                        ),
                        LanguageCode.EN: (
                            "Selected standard names/codes were not found in tender text. "
                            "The list is in evidence — this is not a contract sentence."
                        ),
                        LanguageCode.DE: (
                            "Namen/Codes der gewählten Standards fehlen im Ausschreibungstext. "
                            "Liste in der Evidenz — kein Vertragssatz."
                        ),
                        LanguageCode.FR: (
                            "Noms/codes des normes sélectionnées absents du texte d'AO. "
                            "Liste dans les preuves — ce n'est pas une phrase contractuelle."
                        ),
                    }[lang],
                    source_document_name=None,
                    source_page=None,
                    data_completeness_caveat=caveat,
                ),
                likelihood=RiskSeverity.HIGH,
                financial_impact="high",
                schedule_impact="medium",
                lang=lang,
            )
        )

    if weak_content:
        preview = "؛ ".join(weak_content[:12])
        more = f" (+{len(weak_content) - 12})" if len(weak_content) > 12 else ""
        findings.append(
            apply_composed_risk(
                RiskFinding(
                    code="STD-CONTENT-GAP-001",
                    category="compliance",
                    severity=RiskSeverity.MEDIUM,
                    finding_category="risk",
                    title={
                        LanguageCode.FA: "هم‌پوشانی محتوایی اسناد با PDF استانداردهای انتخاب‌شده ضعیف است",
                        LanguageCode.EN: "Weak content overlap between tender docs and selected standard PDFs",
                        LanguageCode.DE: "Geringe inhaltliche Überlappung Tender / Standard-PDFs",
                        LanguageCode.FR: "Faible chevauchement contenu AO / PDF des normes",
                    }[lang],
                    description={
                        LanguageCode.FA: (
                            f"متن استخراج‌شده از PDF استاندارد برای {len(weak_content)} مورد با اسناد مناقصه "
                            f"هم‌خوانی کافی ندارد: {preview}{more}"
                        ),
                        LanguageCode.EN: (
                            f"Extracted PDF text for {len(weak_content)} selected standards has weak overlap "
                            f"with tender documents: {preview}{more}"
                        ),
                        LanguageCode.DE: (
                            f"Schwache Überlappung für {len(weak_content)} Standards: {preview}{more}"
                        ),
                        LanguageCode.FR: (
                            f"Faible chevauchement pour {len(weak_content)} normes: {preview}{more}"
                        ),
                    }[lang],
                    recommendation={
                        LanguageCode.FA: (
                            "الزامات کلیدی همان استاندارد (ردیف‌ها، حدود، آزمون‌ها، ایمنی) را در مشخصات فنی "
                            "و شرایط خصوصی منعکس کنید؛ فقط بارگذاری PDF در کاتالوگ کافی نیست."
                        ),
                        LanguageCode.EN: (
                            "Reflect key requirements from those standard PDFs in specs/particular conditions; "
                            "uploading the catalog PDF alone is not enough."
                        ),
                        LanguageCode.DE: (
                            "Kernanforderungen der Standard-PDFs in Specs/besondere Bedingungen übernehmen."
                        ),
                        LanguageCode.FR: (
                            "Reprendre les exigences clés des PDF de normes dans le CCTP / conditions particulières."
                        ),
                    }[lang],
                    evidence=preview,
                    source_excerpt={
                        LanguageCode.FA: (
                            "متن PDF استاندارد با اسناد مناقصه هم‌پوشانی کافی ندارد. "
                            "فهرست استانداردهای مربوط در شواهد آمده است."
                        ),
                        LanguageCode.EN: (
                            "Catalog standard PDF text has weak overlap with tender docs. "
                            "Related standards are listed in evidence."
                        ),
                        LanguageCode.DE: (
                            "Geringe Überlappung zwischen Standard-PDF und Ausschreibung. "
                            "Liste in der Evidenz."
                        ),
                        LanguageCode.FR: (
                            "Faible chevauchement entre PDF de norme et AO. "
                            "Liste dans les preuves."
                        ),
                    }[lang],
                    source_document_name=None,
                    source_page=None,
                    data_completeness_caveat=caveat,
                ),
                likelihood=RiskSeverity.MEDIUM,
                financial_impact="medium",
                schedule_impact="medium",
                lang=lang,
            )
        )

    # Methodology footer (not a risk card)
    names = "؛ ".join((s.get("title") or s.get("code") or "") for s in selected_standards[:15])
    more = f" (+{len(selected_standards) - 15})" if len(selected_standards) > 15 else ""
    used_pdf = sum(1 for s in selected_standards if (s.get("extracted_text") or "").strip())
    findings.append(
        RiskFinding(
            code="STD-SELECT-001",
            category="process",
            severity=RiskSeverity.LOW,
            finding_category="methodology",
            title={
                LanguageCode.FA: "استانداردهای انتخاب‌شده برای این تحلیل",
                LanguageCode.EN: "Standards selected for this analysis",
                LanguageCode.DE: "Für diese Analyse gewählte Standards",
                LanguageCode.FR: "Normes sélectionnées pour cette analyse",
            }[lang],
            description={
                LanguageCode.FA: (
                    f"{names}{more}"
                    + (
                        f" — متن PDF کاتالوگ برای {used_pdf} مورد در تحلیل استفاده شد."
                        if used_pdf
                        else " — هنوز متن PDF کاتالوگ استخراج/استفاده نشده است."
                    )
                ),
                LanguageCode.EN: (
                    f"{names}{more}"
                    + (
                        f" — catalog PDF text used for {used_pdf} standard(s)."
                        if used_pdf
                        else " — catalog PDF text not yet extracted/used."
                    )
                ),
                LanguageCode.DE: f"{names}{more}",
                LanguageCode.FR: f"{names}{more}",
            }[lang],
            recommendation={
                LanguageCode.FA: "این مورد ریسک نیست؛ فقط فهرست روش کار است.",
                LanguageCode.EN: "Not a risk — methodology checklist only.",
                LanguageCode.DE: "Kein Risiko — nur Methodik-Checkliste.",
                LanguageCode.FR: "Pas un risque — liste méthodologique uniquement.",
            }[lang],
            evidence=names,
            risk_score=None,
        )
    )
    return findings


def _apply_rule(
    rule: RuleDef,
    *,
    by_cat: dict,
    corpus: str,
    lang: LanguageCode,
    caveat: str | None,
    documents: list[dict] | None = None,
) -> RiskFinding | None:
    only_if = (rule.logic_config or {}).get("only_if_category")
    if only_if:
        try:
            needed = only_if if isinstance(only_if, DocumentCategory) else DocumentCategory(str(only_if))
        except ValueError:
            needed = None
        if needed is not None and not by_cat.get(needed):
            return None

    if rule.requires_category:
        cfg = rule.logic_config or {}
        ownership = str(cfg.get("ownership_tag") or "").upper()
        check = str(cfg.get("check") or "").strip()
        # Pattern / seed rules must NEVER invent per-pattern findings when the
        # base document category is absent. Completeness engines emit at most
        # one "document X missing" finding (SCHED-001 / DRAW-001 / STD-001).
        is_pattern_rule = ownership in {"PYTHON", "AI", "HYBRID"} or (
            check
            and check
            not in {
                "missing_category",
                "keywords_missing",
            }
        )
        if not by_cat.get(rule.requires_category):
            if is_pattern_rule:
                return None
            chain = []
            if rule.severity in {RiskSeverity.HIGH, RiskSeverity.MEDIUM}:
                chain = [
                    {
                        LanguageCode.FA: f"سند الزامی ({rule.requires_category.value}) موجود نیست",
                        LanguageCode.EN: f"Required document ({rule.requires_category.value}) missing",
                        LanguageCode.DE: f"Erforderliches Dokument fehlt ({rule.requires_category.value})",
                        LanguageCode.FR: f"Document requis manquant ({rule.requires_category.value})",
                    }[lang],
                    {
                        LanguageCode.FA: "ابهام در مناقصه و اجرا",
                        LanguageCode.EN: "Ambiguity at tender and on site",
                        LanguageCode.DE: "Unklarheit in Ausschreibung und Ausführung",
                        LanguageCode.FR: "Ambiguïté à l'AO et sur chantier",
                    }[lang],
                    {
                        LanguageCode.FA: "ادعا / تأخیر / هزینه اضافی",
                        LanguageCode.EN: "Claim / delay / extra cost",
                        LanguageCode.DE: "Claim / Verzug / Mehrkosten",
                        LanguageCode.FR: "Réclamation / retard / surcoût",
                    }[lang],
                ]
            return apply_composed_risk(
                RiskFinding(
                    code=rule.code,
                    category=rule.category,
                    severity=rule.severity,
                    finding_category="risk",
                    title=_lang(rule.title, lang),
                    description=_lang(rule.description, lang),
                    recommendation=_lang(rule.recommendation, lang),
                    cause_effect_chain=chain,
                    data_completeness_caveat=caveat,
                    source_document_name={
                        LanguageCode.FA: f"— (فایل «{_category_label(rule.requires_category, lang)}» بارگذاری نشده)",
                        LanguageCode.EN: f"— (no «{_category_label(rule.requires_category, lang)}» file uploaded)",
                        LanguageCode.DE: f"— (keine «{_category_label(rule.requires_category, lang)}»-Datei)",
                        LanguageCode.FR: f"— (aucun fichier «{_category_label(rule.requires_category, lang)}»)",
                    }[lang][:512],
                    source_excerpt={
                        LanguageCode.FA: (
                            f"در اسناد پروژه هیچ فایلی در دسته «{_category_label(rule.requires_category, lang)}» نیست. "
                            + (
                                f"اسناد فعلی: {'، '.join(_doc_names(documents or [], limit=6))}."
                                if documents
                                else "برای رفع ریسک، فایل مرجع را بارگذاری کنید."
                            )
                        ),
                        LanguageCode.EN: (
                            f"No project file is in the «{_category_label(rule.requires_category, lang)}» category. "
                            + (
                                f"Current files: {', '.join(_doc_names(documents or [], limit=6))}."
                                if documents
                                else "Upload the required reference file."
                            )
                        ),
                        LanguageCode.DE: (
                            f"Keine Datei in Kategorie «{_category_label(rule.requires_category, lang)}». "
                            + (
                                f"Vorhanden: {', '.join(_doc_names(documents or [], limit=6))}."
                                if documents
                                else "Bitte Referenzdatei hochladen."
                            )
                        ),
                        LanguageCode.FR: (
                            f"Aucun fichier dans la catégorie «{_category_label(rule.requires_category, lang)}». "
                            + (
                                f"Fichiers actuels: {', '.join(_doc_names(documents or [], limit=6))}."
                                if documents
                                else "Téléversez le fichier de référence."
                            )
                        ),
                    }[lang],
                    evidence=None,
                ),
                likelihood=rule.severity,
                financial_impact=rule.financial_impact,
                schedule_impact=rule.schedule_impact,
                lang=lang,
            )
        # Category present: completeness-only rules do not fire; pattern rules
        # are owned by the PYTHON/AI engines (skipped in the keyword loop).
        return None

    keywords = rule.keywords_any or []
    if keywords and not _contains_any(corpus, keywords):
        # Attribute to the primary tender/readable file and surface a nearby quote
        # (related topic terms) so the report card is actionable.
        related_hints = list(keywords) + [
            w
            for w in re.findall(r"[\w\u0600-\u06FF]{4,}", _lang(rule.title, lang))
            if w.lower() not in {"iran", "ایران"}
        ][:8]
        soft_cats = ("tender",)
        if rule.requires_category:
            soft_cats = (rule.requires_category.value, "tender")
        doc_name, excerpt, page = locate_document_excerpt(
            documents or [],
            keywords=related_hints,
            prefer_categories=soft_cats,
        )
        if not excerpt:
            missing_note = {
                LanguageCode.FA: f"عبارت‌های الزامی در متن فایل یافت نشد: {'، '.join(keywords[:6])}",
                LanguageCode.EN: f"Required phrases not found in file text: {', '.join(keywords[:6])}",
                LanguageCode.DE: f"Erforderliche Phrasen nicht gefunden: {', '.join(keywords[:6])}",
                LanguageCode.FR: f"Expressions requises introuvables: {', '.join(keywords[:6])}",
            }[lang]
            excerpt = missing_note
        return apply_composed_risk(
            RiskFinding(
                code=rule.code,
                category=rule.category,
                severity=rule.severity,
                finding_category="risk",
                title=_lang(rule.title, lang),
                description=_lang(rule.description, lang),
                recommendation=_lang(rule.recommendation, lang),
                evidence=(f"{doc_name}: {excerpt}" if doc_name else excerpt)[:2000],
                source_excerpt=(excerpt or "")[:800] or None,
                source_document_name=doc_name,
                source_page=page,
                cause_effect_chain=[
                    {
                        LanguageCode.FA: "الزام قراردادی/فنی در متن دیده نشد",
                        LanguageCode.EN: "Required contractual/technical element not found in text",
                        LanguageCode.DE: "Erforderliches Element im Text nicht gefunden",
                        LanguageCode.FR: "Élément requis absent du texte",
                    }[lang],
                    {
                        LanguageCode.FA: "تفسیر متفاوت طرفین",
                        LanguageCode.EN: "Divergent party interpretations",
                        LanguageCode.DE: "Abweichende Auslegungen",
                        LanguageCode.FR: "Interprétations divergentes",
                    }[lang],
                    {
                        LanguageCode.FA: "اختلاف و تأخیر محتمل",
                        LanguageCode.EN: "Likely dispute and delay",
                        LanguageCode.DE: "Streit und Verzug wahrscheinlich",
                        LanguageCode.FR: "Litige et retard probables",
                    }[lang],
                ]
                if rule.severity != RiskSeverity.LOW
                else [],
                data_completeness_caveat=caveat,
            ),
            likelihood=rule.severity,
            financial_impact=rule.financial_impact,
            schedule_impact=rule.schedule_impact,
            lang=lang,
        )
    return None


def _dedupe_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    seen: set[str] = set()
    out: list[RiskFinding] = []
    for f in findings:
        if f.code in seen:
            continue
        seen.add(f.code)
        out.append(f)
    return out


def analyze_project_documents(
    *,
    country: CountryCode,
    report_language: LanguageCode,
    documents: list[dict],
    project_type: ProjectType | None = None,
    selected_standards: list[dict] | None = None,
) -> dict:
    lang = report_language
    ptype = project_type or ProjectType.INFRASTRUCTURE
    profile = get_country_profile(country)
    selected_standards = selected_standards or []

    by_cat: dict[DocumentCategory, list[dict]] = {c: [] for c in DocumentCategory}
    for doc in documents:
        cat = doc["category"]
        if not isinstance(cat, DocumentCategory):
            cat = DocumentCategory(str(cat))
        by_cat[cat].append({**doc, "category": cat})

    stats = _extraction_stats(documents)
    gate_rate = float(stats["gate_rate"])
    failed_names = stats["failed_names"]

    templates = {
        cat.value: resolve_document_template(category=cat, country=country, project_type=ptype).code
        for cat in DocumentCategory
    }

    # ---------- FIX 1: hard gate ----------
    if stats["total"] == 0 or gate_rate < _EXTRACTION_HARD_GATE:
        failed_list = "، ".join(failed_names[:12])
        more = f" (+{len(failed_names) - 12})" if len(failed_names) > 12 else ""
        block = RiskFinding(
            code="EXTRACT-BLOCK-001",
            category="process",
            severity=RiskSeverity.HIGH,
            finding_category="limitation",
            title={
                LanguageCode.FA: "تحلیل کامل امکان‌پذیر نیست",
                LanguageCode.EN: "Full analysis is not possible",
                LanguageCode.DE: "Vollständige Analyse nicht möglich",
                LanguageCode.FR: "Analyse complète impossible",
            }[lang],
            description={
                LanguageCode.FA: (
                    f"از {stats.get('text_doc_count', stats['total'])} سند متنی "
                    f"(نقشه‌ها جدا حساب می‌شوند)، {stats['failed_count']} قابل خواندن نبود "
                    f"(≈ {int(gate_rate * 100)}٪). "
                    f"تعداد نقشه: {stats.get('drawing_count', 0)}. "
                    f"نمونه فایل‌های ناموفق: {failed_list}{more}"
                ),
                LanguageCode.EN: (
                    f"Of {stats.get('text_doc_count', stats['total'])} text documents "
                    f"(drawings excluded), {stats['failed_count']} unreadable "
                    f"(≈ {int(gate_rate * 100)}%). Drawings: {stats.get('drawing_count', 0)}. "
                    f"Sample: {failed_list}{more}"
                ),
                LanguageCode.DE: (
                    f"{stats['failed_count']}/{stats.get('text_doc_count', stats['total'])} Textdocs unlesbar "
                    f"(≈ {int(gate_rate * 100)}٪). Beispiel: {failed_list}{more}"
                ),
                LanguageCode.FR: (
                    f"{stats['failed_count']}/{stats.get('text_doc_count', stats['total'])} docs texte illisibles "
                    f"(≈ {int(gate_rate * 100)}٪). Exemples: {failed_list}{more}"
                ),
            }[lang],
            recommendation={
                LanguageCode.FA: "اسناد مناقصه را Word یا PDF متنی بارگذاری کنید و «استخراج مجدد» بزنید. نقشه‌های بدون متن مانع تحلیل نیستند.",
                LanguageCode.EN: "Upload tender docs as Word/text PDF and use Re-extract. Drawings without text do not block analysis.",
                LanguageCode.DE: "Ausschreibung als Word/Text-PDF laden und erneut extrahieren. Pläne ohne Text blockieren nicht.",
                LanguageCode.FR: "Charger l'AO en Word/PDF texte et ré-extraire. Les plans sans texte ne bloquent pas.",
            }[lang],
            evidence=failed_list,
            source_excerpt=failed_list[:400],
            risk_score=None,
        )
        blocked_pct = int(round(gate_rate * 100))
        summary = {
            LanguageCode.FA: (
                f"تحلیل مسدود شد. {_extraction_readiness_clause(stats, blocked_pct, LanguageCode.FA)} "
                f"ریسک محتوایی ادعا نشد."
            ),
            LanguageCode.EN: (
                f"Analysis blocked. {_extraction_readiness_clause(stats, blocked_pct, LanguageCode.EN)} "
                f"No content risks claimed."
            ),
            LanguageCode.DE: (
                f"Analyse blockiert. {_extraction_readiness_clause(stats, blocked_pct, LanguageCode.DE)}"
            ),
            LanguageCode.FR: (
                f"Analyse bloquée. {_extraction_readiness_clause(stats, blocked_pct, LanguageCode.FR)}"
            ),
        }[lang]
        return {
            "summary": summary,
            "readiness_score": int(round(gate_rate * 100)),
            "analysis_status": "blocked",
            "text_extraction_success_rate": gate_rate,
            "counts": {"high": 0, "medium": 0, "low": 0, "total": 0},
            "counts_risk": {"high": 0, "medium": 0, "low": 0, "total": 0},
            "aggregate_risk_score": None,
            "documents_with_limitations": stats["limitation_count"],
            "findings": [block],
            "engine": {
                "country_profile": profile_snapshot(country, ptype),
                "blocked": True,
                "extraction": stats,
                "document_templates": templates,
                "selected_standards": [s.get("code") for s in selected_standards],
            },
        }

    caveat = None
    if gate_rate < _EXTRACTION_SOFT_GATE:
        caveat = {
            LanguageCode.FA: (
                f"هشدار کامل‌بودن داده: فقط {stats['readable_count']} از {stats.get('text_doc_count', stats['total'])} سند متنی قابل‌استفاده داشتند. "
                f"یافته‌ها فقط روی اسناد خوانا اعتبار دارند. خوانده‌نشده: "
                + "، ".join(failed_names[:12])
                + ("…" if len(failed_names) > 12 else "")
            ),
            LanguageCode.EN: (
                f"Data completeness caveat: only {stats['readable_count']}/{stats.get('text_doc_count', stats['total'])} text docs had usable text. "
                f"Findings are only as reliable as readable sources. Unreadable: "
                + ", ".join(failed_names[:12])
                + ("…" if len(failed_names) > 12 else "")
            ),
            LanguageCode.DE: (
                f"Datenlücke: nur {stats['readable_count']}/{stats['total']} Dateien nutzbar. "
                + ", ".join(failed_names[:12])
            ),
            LanguageCode.FR: (
                f"Limite de complétude: seulement {stats['readable_count']}/{stats['total']} fichiers lisibles. "
                + ", ".join(failed_names[:12])
            ),
        }[lang]

    tender_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.TENDER])
    standard_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.STANDARD])
    schedule_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.SCHEDULE])
    # IFC / DXF / DWG / Revit live under drawing → technical_corpus via drawing_text
    drawing_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.DRAWING])
    # GAEB LV should be uploaded as tender → contract_corpus + technical via tender_text
    # Prefer readable corpus only for rules (includes IFC/CAD/GAEB native text)
    readable_docs = [d for d in documents if has_usable_text(d.get("extracted_text") or "")]
    corpus_for_rules = "\n".join((d.get("extracted_text") or "") for d in readable_docs)

    rules = resolve_rules_for_project(
        country=country,
        project_type=ptype,
        ruleset_code=profile.default_ruleset_code,
    )
    hint_blob = " ".join(profile.config.get("contract_keywords_hint") or [])

    findings: list[RiskFinding] = []

    # Section B — extraction limitation banner (not equal-weight risk)
    if failed_names:
        findings.append(
            RiskFinding(
                code="OCR-001",
                category="process",
                severity=RiskSeverity.MEDIUM,
                finding_category="limitation",
                title={
                    LanguageCode.FA: "محدودیت استخراج متن از برخی فایل‌ها",
                    LanguageCode.EN: "Text extraction limitation on some files",
                    LanguageCode.DE: "Textextraktionsgrenze bei einigen Dateien",
                    LanguageCode.FR: "Limitation d'extraction sur certains fichiers",
                }[lang],
                description={
                    LanguageCode.FA: f"{stats['failed_count']} فایل بدون متن قابل‌استفاده: "
                    + "، ".join(failed_names[:20])
                    + ("…" if len(failed_names) > 20 else ""),
                    LanguageCode.EN: f"{stats['failed_count']} files without usable text: "
                    + ", ".join(failed_names[:20])
                    + ("…" if len(failed_names) > 20 else ""),
                    LanguageCode.DE: f"{stats['failed_count']} Dateien ohne Text: " + ", ".join(failed_names[:20]),
                    LanguageCode.FR: f"{stats['failed_count']} fichiers sans texte: " + ", ".join(failed_names[:20]),
                }[lang],
                recommendation={
                    LanguageCode.FA: "برای نقشه‌های اسکن‌شده OCR فعال کنید؛ برای قراردادها نسخه Word/PDF متنی بارگذاری کنید.",
                    LanguageCode.EN: "Enable OCR for scanned drawings; upload text Word/PDF for contracts.",
                    LanguageCode.DE: "OCR für Pläne; Text-PDF/Word für Verträge.",
                    LanguageCode.FR: "OCR pour plans scannés; Word/PDF texte pour contrats.",
                }[lang],
                evidence="، ".join(failed_names[:20]),
                source_excerpt="، ".join(failed_names[:15]),
                risk_score=None,
                data_completeness_caveat=caveat,
            )
        )

    # FIX 2 — semantic standards (consolidated)
    findings.extend(
        _analyze_selected_standards_semantic(
            lang=lang,
            selected_standards=selected_standards,
            tender_text=tender_text,
            standard_text=standard_text,
            drawing_text=drawing_text,
            caveat=caveat,
        )
    )

    for rule in rules:
        if rule.code == "STD-001" and selected_standards:
            continue
        # Seed/pattern rules are executed by the PYTHON / AI engines — never by
        # the keyword completeness path (avoids N fabricated "doc missing" hits).
        ownership = str((rule.logic_config or {}).get("ownership_tag") or "").upper()
        if ownership in {"PYTHON", "AI", "HYBRID"}:
            continue
        hit = _apply_rule(
            rule,
            by_cat=by_cat,
            corpus=corpus_for_rules,
            lang=lang,
            caveat=caveat,
            documents=readable_docs,
        )
        if hit:
            findings.append(hit)

    if by_cat[DocumentCategory.TENDER] and by_cat[DocumentCategory.SCHEDULE]:
        tender_has_duration = _contains_any(
            tender_text,
            ["مدت", "ماه", "روز", "duration", "weeks", "months", "Fertigstellung", "Bauzeit", "completion"],
        )
        schedule_has_dates = bool(
            re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", schedule_text)
        )
        if tender_has_duration and not schedule_has_dates and has_usable_text(schedule_text):
            findings.append(
                apply_composed_risk(
                    RiskFinding(
                        code="XR-TIME-001",
                        category="schedule",
                        severity=RiskSeverity.MEDIUM,
                        finding_category="risk",
                        title={
                            LanguageCode.FA: "عدم هم‌خوانی مدت پیمان و جزئیات برنامه",
                            LanguageCode.EN: "Mismatch between contract duration and schedule detail",
                            LanguageCode.DE: "Widerspruch Vertragslaufzeit / Terminplan-Detail",
                            LanguageCode.FR: "Écart durée du marché / détail du planning",
                        }[lang],
                        description={
                            LanguageCode.FA: "مدت در اسناد پیمان هست اما برنامه جزئیات تاریخ کافی ندارد.",
                            LanguageCode.EN: "Duration exists in tender docs but schedule lacks date detail.",
                            LanguageCode.DE: "Laufzeit genannt, Terminplan ohne ausreichende Daten.",
                            LanguageCode.FR: "Durée citée mais planning sans dates suffisantes.",
                        }[lang],
                        recommendation={
                            LanguageCode.FA: "در برنامه مبنا تاریخ شروع/پایان و مایلستون‌های هم‌تراز با مدت پیمان را صریح بنویسید.",
                            LanguageCode.EN: "State start/finish and milestones in the baseline aligned to contract duration.",
                            LanguageCode.DE: "Start/Ende und Meilensteine im Basisterminplan zur Vertragslaufzeit festlegen.",
                            LanguageCode.FR: "Fixer début/fin et jalons alignés sur la durée contractuelle.",
                        }[lang],
                        cause_effect_chain=[
                            {
                                LanguageCode.FA: "مدت پیمان بدون برنامه تاریخ‌دار",
                                LanguageCode.EN: "Contract duration without dated programme",
                                LanguageCode.DE: "Laufzeit ohne datierten Terminplan",
                                LanguageCode.FR: "Durée sans planning daté",
                            }[lang],
                            {
                                LanguageCode.FA: "اختلاف در تمدید مدت / تأخیر",
                                LanguageCode.EN: "Dispute on EOT / delay",
                                LanguageCode.DE: "Streit um Verlängerung / Verzug",
                                LanguageCode.FR: "Litige prolongation / retard",
                            }[lang],
                            {
                                LanguageCode.FA: "هزینه تأخیر برای کارفرما",
                                LanguageCode.EN: "Delay cost to employer",
                                LanguageCode.DE: "Verzugskosten für Auftraggeber",
                                LanguageCode.FR: "Coût de retard pour le maître d'ouvrage",
                            }[lang],
                        ],
                        data_completeness_caveat=caveat,
                    ),
                    likelihood=RiskSeverity.MEDIUM,
                    financial_impact="medium",
                    schedule_impact="high",
                    lang=lang,
                )
            )

    findings = _dedupe_findings(findings)
    findings = enrich_findings_document_sources(findings, documents, lang=lang)

    risks = [f for f in findings if f.finding_category == "risk"]
    high = sum(1 for f in risks if f.severity == RiskSeverity.HIGH)
    medium = sum(1 for f in risks if f.severity == RiskSeverity.MEDIUM)
    low = sum(1 for f in risks if f.severity == RiskSeverity.LOW)
    scores = [f.risk_score for f in risks if f.risk_score is not None]
    aggregate = int(round(sum(scores) / len(scores))) if scores else 0
    # Readiness = success among text docs only (drawings excluded from the gate)
    readiness = int(round(gate_rate * 100))
    extract_clause = _extraction_readiness_clause(stats, readiness, lang)

    summary = {
        LanguageCode.FA: (
            f"{extract_clause} "
            f"ریسک‌های واقعی: {high} بالا، {medium} متوسط، {low} پایین "
            f"(میانگین امتیاز ریسک: {aggregate}). "
            f"اسناد با محدودیت استخراج: {stats['limitation_count']} فایل"
            f" (بدون متن قابل‌استفاده: {stats['failed_count']}؛ اطمینان پایین: {stats.get('low_confidence_count', 0)}). "
            f"پروفایل: {profile.code}."
        ),
        LanguageCode.EN: (
            f"{extract_clause} "
            f"Real risks: {high} high, {medium} medium, {low} low "
            f"(avg risk score: {aggregate}). "
            f"Documents with extraction limitations: {stats['limitation_count']} files"
            f" (unusable text: {stats['failed_count']}; low confidence: {stats.get('low_confidence_count', 0)}). "
            f"Profile: {profile.code}."
        ),
        LanguageCode.DE: (
            f"{extract_clause} "
            f"Echte Risiken: {high}/{medium}/{low} (Ø {aggregate}). "
            f"Extraktions-Limitierungen: {stats['limitation_count']} "
            f"(ohne Text: {stats['failed_count']}; niedrige Konfidenz: {stats.get('low_confidence_count', 0)}). "
            f"Profil: {profile.code}."
        ),
        LanguageCode.FR: (
            f"{extract_clause} "
            f"Risques réels: {high}/{medium}/{low} (moy. {aggregate}). "
            f"Limitations d'extraction: {stats['limitation_count']} "
            f"(texte inutilisable: {stats['failed_count']}; confiance basse: {stats.get('low_confidence_count', 0)}). "
            f"Profil: {profile.code}."
        ),
    }[lang]

    prompt_bundle = render_prompt_bundle(
        code="ANALYZE_RESPONSIBILITY_CLAUSES",
        country=country,
        project_type=ptype,
        extracted_text_excerpt=tender_text or hint_blob,
    )

    return {
        "summary": summary,
        "readiness_score": readiness,
        "analysis_status": "completed",
        "text_extraction_success_rate": gate_rate,
        "counts": {"high": high, "medium": medium, "low": low, "total": len(risks)},
        "counts_risk": {"high": high, "medium": medium, "low": low, "total": len(risks)},
        "aggregate_risk_score": aggregate,
        "documents_with_limitations": stats["limitation_count"],
        "findings": findings,
        "engine": {
            "country_profile": profile_snapshot(country, ptype),
            "ruleset": profile.default_ruleset_code,
            "resolved_rules": [r.code for r in rules],
            "document_templates": templates,
            "selected_standards": [s.get("code") for s in selected_standards],
            "extraction": stats,
            "data_completeness_caveat": caveat,
            "prompt_bundle": {
                "template_code": prompt_bundle["template_code"],
                "resolved_country_scope": prompt_bundle["resolved_country_scope"],
                "context_pack": prompt_bundle["context_pack"],
            },
        },
    }
