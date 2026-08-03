"""Phase 7 — Human Construction Experience Knowledge layer.

Surfaces matching ExperienceKnowledgeItem rows as advisory findings
(finding_category=experience, source_layer=experience_based).
Not mandatory rules — clearly labeled for the Rule Engine / analysis merge.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ExperienceKnowledgeItem, LanguageCode, ProjectType, RiskSeverity
from app.services.analyzer import RiskFinding

logger = logging.getLogger(__name__)

# Surface these statuses; rejected/archived stay silent
_SURFACEABLE_STATUSES = frozenset(
    {"validated", "approved", "draft", "pending_review", "expert_reviewed"}
)

_ORIGIN_ALIASES = {
    "extracted_insight": "external_extracted",
    "external_insight": "external_extracted",
    "project_lesson": "project_derived",
    "expert_observation": "expert_reviewed",
    "failure_pattern": "admin_curated",
    "claim_pattern": "admin_curated",
}


def normalize_origin_kind(value: str | None) -> str:
    raw = (value or "admin_curated").strip().lower()
    return _ORIGIN_ALIASES.get(raw, raw)


def _loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(x) for x in val]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
    except json.JSONDecodeError:
        return [p.strip() for p in raw.split(",") if p.strip()]
    return []


def item_to_dict(item: ExperienceKnowledgeItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "experience_id": item.experience_id,
        "title": item.title,
        "description": item.description,
        "category": item.category,
        "origin_kind": item.origin_kind,
        "source": item.source,
        "author": item.author,
        "validation_status": item.validation_status,
        "confidence_level": item.confidence_level,
        "related_risk_id": item.related_risk_id,
        "related_risk_category": item.related_risk_category,
        "related_project_types": _loads_list(item.related_project_types_json),
        "recommended_prevention": item.recommended_prevention,
        "related_documents": _loads_list(item.related_documents_json),
        "related_outcomes": _loads_list(item.related_outcomes_json),
        "match_keywords": _loads_list(getattr(item, "match_keywords_json", None)),
        "version": item.version,
        "is_active": item.is_active,
    }


# Category taxonomy for admin curation + auto-suggest
EXPERIENCE_CATEGORIES: dict[str, list[str]] = {
    "schedule": [
        "schedule", "programme", "program", "gantt", "float", "milestone", "delay", "eot",
        "زمان", "برنامه", "تأخیر", "مایلستون", "شناوری", "مدت",
    ],
    "boq_cost": [
        "boq", "quantity", "unit price", "meter", "fehrest", "gaeb", "cost", "price",
        "متره", "برآورد", "قیمت", "ردیف", "صورت وضعیت", "مبلغ",
    ],
    "drawing_technical": [
        "drawing", "ifc", "dxf", "dwg", "detail", "section", "scale", "revision",
        "نقشه", "جزئیات", "مقطع", "مقیاس", "نسخه نقشه",
    ],
    "contract_claims": [
        "contract", "claim", "variation", "ld", "liquidated", "scope", "responsibility",
        "پیمان", "قرارداد", "ادعا", "تغییر کار", "جریمه", "مسئولیت", "شرایط خصوصی",
    ],
    "standards_compliance": [
        "standard", "code", "nbc", "din", "iso", "regulation", "مبحث", "استاندارد", "آیین",
    ],
    "safety_hse": [
        "safety", "fire", "hse", "evacuation", "ایمنی", "حریق", "آتش", "حفاظت",
    ],
    "geotech_foundation": [
        "geotech", "soil", "foundation", "pile", "bearing", "ژئوتکنیک", "خاک", "پی", "فونداسیون",
    ],
    "procurement_tender": [
        "tender", "bid", "itt", "addendum", "deadline", "مناقصه", "پیشنهاد", "الحاقیه", "مهلت",
    ],
}


def suggest_category(text: str) -> str:
    blob = (text or "").lower()
    best = "lesson"
    best_hits = 0
    for cat, kws in EXPERIENCE_CATEGORIES.items():
        hits = sum(1 for k in kws if k.lower() in blob)
        if hits > best_hits:
            best_hits = hits
            best = cat
    return best


def suggest_match_keywords(text: str, *, limit: int = 12) -> list[str]:
    """Pull distinctive tokens/phrases for document scanning."""
    raw = (text or "").strip()
    if not raw:
        return []
    # Prefer taxonomy hits present in text
    found: list[str] = []
    lower = raw.lower()
    for kws in EXPERIENCE_CATEGORIES.values():
        for k in kws:
            if k.lower() in lower and k not in found:
                found.append(k)
            if len(found) >= limit:
                return found
    # Fall back to significant words from title-like first line
    first = raw.splitlines()[0] if raw else ""
    tokens = re.findall(r"[\w\u0600-\u06FF]{4,}", first)
    for tkn in tokens:
        if tkn.lower() not in {x.lower() for x in found}:
            found.append(tkn)
        if len(found) >= limit:
            break
    return found[:limit]


def parse_bulk_experience_text(raw: str) -> list[dict[str, str]]:
    """Split pasted text into experience blocks.

    Separators: a line with only --- / === / *** , or 2+ blank lines.
    First non-empty line of each block → title; rest → description.
    """
    text = (raw or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    # Normalize separators to a sentinel
    text = re.sub(r"\n[ \t]*[-*=]{3,}[ \t]*\n", "\n\n@@SPLIT@@\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n@@SPLIT@@\n\n", text)
    chunks = [c.strip() for c in text.split("@@SPLIT@@") if c.strip()]
    out: list[dict[str, str]] = []
    for chunk in chunks:
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        title = lines[0][:512]
        description = "\n".join(lines[1:]).strip() if len(lines) > 1 else lines[0]
        if len(title) < 3:
            title = (description[:80] + "…") if len(description) > 80 else description
        out.append({"title": title, "description": description})
    return out


def suggest_title_from_text(text: str) -> str:
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "") or "Experience"
    return first[:512]


def _confidence_to_score(level: str | None) -> int:
    key = (level or "medium").strip().lower()
    if key.isdigit():
        return max(0, min(100, int(key)))
    return {"high": 80, "medium": 55, "low": 35}.get(key, 55)


def _severity_from_confidence(level: str | None) -> RiskSeverity:
    score = _confidence_to_score(level)
    if score >= 70:
        return RiskSeverity.MEDIUM  # experience never auto-escalates to HIGH mandatory
    if score >= 40:
        return RiskSeverity.MEDIUM
    return RiskSeverity.LOW


def _extract_risk_ids_from_findings(findings: list[Any]) -> set[str]:
    out: set[str] = set()
    for f in findings or []:
        chain = getattr(f, "cause_effect_chain", None) or []
        if isinstance(chain, str):
            try:
                chain = json.loads(chain)
            except json.JSONDecodeError:
                chain = [chain]
        for bit in chain:
            m = re.search(r"risk_id=([A-Za-z0-9_\-]+)", str(bit))
            if m:
                out.add(m.group(1))
        evidence = str(getattr(f, "evidence", "") or "")
        for m in re.finditer(r"(RISK-[A-Z0-9_\-]+)", evidence):
            out.add(m.group(1))
    return out


def _extract_categories_from_findings(findings: list[Any]) -> set[str]:
    cats: set[str] = set()
    for f in findings or []:
        cat = getattr(f, "category", None)
        if cat:
            cats.add(str(cat).strip().lower())
    return cats


def item_matches_project(
    item: ExperienceKnowledgeItem | dict[str, Any],
    *,
    project_type: str | ProjectType | None,
    finding_risk_ids: set[str],
    finding_categories: set[str],
    document_corpus: str | None = None,
) -> bool:
    """True when project type, related risk, or document keywords align.

    Criteria are OR'd so curated lessons can surface from type, risk, or
    document-text keyword hits (gap/ambiguity scan — like standards selection).
    """
    if isinstance(item, ExperienceKnowledgeItem):
        types = _loads_list(item.related_project_types_json)
        risk_id = (item.related_risk_id or "").strip()
        risk_cat = (item.related_risk_category or "").strip().lower()
        status = (item.validation_status or "").strip().lower()
        active = bool(item.is_active)
        keywords = _loads_list(getattr(item, "match_keywords_json", None))
        category = (item.category or "").strip().lower()
    else:
        types = [str(t) for t in (item.get("related_project_types") or [])]
        risk_id = str(item.get("related_risk_id") or "").strip()
        risk_cat = str(item.get("related_risk_category") or "").strip().lower()
        status = str(item.get("validation_status") or "").strip().lower()
        active = bool(item.get("is_active", True))
        keywords = [str(k) for k in (item.get("match_keywords") or [])]
        category = str(item.get("category") or "").strip().lower()

    if not active or status not in _SURFACEABLE_STATUSES:
        return False

    ptype = project_type.value if isinstance(project_type, ProjectType) else str(project_type or "")
    ptype = ptype.strip().lower()

    type_hit = bool(types) and ptype in {t.strip().lower() for t in types}
    risk_hit = bool(risk_id) and risk_id in finding_risk_ids
    cat_hit = bool(risk_cat) and risk_cat in finding_categories

    corpus = (document_corpus or "").lower()
    kw_hit = False
    if corpus and keywords:
        kw_hit = any(k.strip().lower() in corpus for k in keywords if k.strip())
    # Category taxonomy tokens as soft document scan when no explicit keywords
    if corpus and not keywords and category in EXPERIENCE_CATEGORIES:
        soft = EXPERIENCE_CATEGORIES[category]
        kw_hit = sum(1 for k in soft if k.lower() in corpus) >= 2

    configured = bool(types) or bool(risk_id) or bool(risk_cat) or bool(keywords) or bool(category)
    if not configured:
        return False
    # Always-on lessons: category set, no type/risk/keywords → match all projects
    if category and not types and not risk_id and not risk_cat and not keywords:
        return True
    return type_hit or risk_hit or cat_hit or kw_hit


def experience_to_finding(
    item: ExperienceKnowledgeItem,
    *,
    lang: LanguageCode = LanguageCode.EN,
) -> RiskFinding:
    """Build an advisory experience finding — NOT a mandatory rule."""
    conf = _confidence_to_score(item.confidence_level)
    prevention = (item.recommended_prevention or "").strip() or {
        LanguageCode.FA: "این الگوی تاریخی را هنگام شفاف‌سازی مناقصه بررسی کنید؛ صرفاً مشورتی است.",
        LanguageCode.EN: "Review this historical pattern during tender clarification; it is advisory only.",
        LanguageCode.DE: "Dieses historische Muster bei der Ausschreibungsklärung prüfen; nur beratend.",
        LanguageCode.FR: "Examiner ce schéma historique lors des clarifications; avis consultatif uniquement.",
    }.get(lang, "Review this historical pattern during tender clarification; it is advisory only.")
    types = _loads_list(item.related_project_types_json)
    eid = item.experience_id
    # Avoid EXP-EXP-… if experience_id already has EXP- prefix
    code = eid if eid.upper().startswith("EXP-") else f"EXP-{eid}"
    prefix = {
        LanguageCode.FA: "مبتنی بر تجربه (قاعده اجباری نیست).",
        LanguageCode.EN: "EXPERIENCE-BASED (not a mandatory rule).",
        LanguageCode.DE: "ERFAHRUNGSBASIERT (keine Pflichtregel).",
        LanguageCode.FR: "BASÉ SUR L'EXPÉRIENCE (pas une règle obligatoire).",
    }.get(lang, "EXPERIENCE-BASED (not a mandatory rule).")
    intro = {
        LanguageCode.FA: "این الگو در پروژه‌های قبلی مشکل ایجاد کرده است.",
        LanguageCode.EN: "This pattern has caused issues in previous projects.",
        LanguageCode.DE: "Dieses Muster hat in früheren Projekten Probleme verursacht.",
        LanguageCode.FR: "Ce schéma a déjà causé des problèmes sur des projets antérieurs.",
    }.get(lang, "This pattern has caused issues in previous projects.")
    title_prefix = {
        LanguageCode.FA: "[تجربه]",
        LanguageCode.EN: "[Experience]",
        LanguageCode.DE: "[Erfahrung]",
        LanguageCode.FR: "[Expérience]",
    }.get(lang, "[Experience]")
    caveat = {
        LanguageCode.FA: "فقط شاخص تجربه — جایگزین انطباق با استاندارد یا شواهد پروژه نیست.",
        LanguageCode.EN: "Experience indicator only — does not replace standards compliance or project evidence.",
        LanguageCode.DE: "Nur Erfahrungsindikator — ersetzt nicht Normkonformität oder Projekthinweise.",
        LanguageCode.FR: "Indicateur d'expérience uniquement — ne remplace pas la conformité normative.",
    }.get(lang, "Experience indicator only — does not replace standards compliance or project evidence.")
    desc = (
        f"{prefix} {intro} "
        f"{item.description.strip()} "
        f"[validation_status={item.validation_status}; origin_kind={item.origin_kind}; "
        f"confidence={item.confidence_level}]"
    )
    evidence = (
        f"experience_id={eid}; related_project_types={types}; "
        f"related_risk_id={item.related_risk_id or '—'}; "
        f"source={item.source or 'admin'}; author={item.author or '—'}"
    )
    return RiskFinding(
        code=code,
        category=item.category or "experience",
        severity=_severity_from_confidence(item.confidence_level),
        title=f"{title_prefix} {item.title}",
        description=desc,
        recommendation=prevention,
        financial_impact=None,
        schedule_impact=None,
        evidence=evidence[:2000],
        finding_category="experience",
        risk_score=conf,
        source_excerpt=item.description[:800],
        cause_effect_chain=[
            f"experience_id={eid}",
            f"origin_kind={item.origin_kind}",
            f"validation_status={item.validation_status}",
            f"related_risk_id={item.related_risk_id or ''}",
            "source_layer=experience_based",
            "advisory=true",
            "mandatory_rule=false",
        ],
        source_layer="experience_based",
        confidence_score=conf,
        data_completeness_caveat=caveat,
    )


async def list_active_experience_items(db: AsyncSession) -> list[ExperienceKnowledgeItem]:
    rows = (
        await db.execute(
            select(ExperienceKnowledgeItem)
            .where(ExperienceKnowledgeItem.is_active.is_(True))
            .order_by(ExperienceKnowledgeItem.experience_id)
        )
    ).scalars().all()
    return list(rows)


async def match_experience_findings(
    db: AsyncSession,
    *,
    project_type: str | ProjectType | None,
    existing_findings: list[Any] | None = None,
    document_corpus: str | None = None,
    lang: LanguageCode = LanguageCode.EN,
) -> list[RiskFinding]:
    """
    When EXPERIENCE_LAYER_ENABLED, return advisory findings for matching items.
    Empty list when flag is off.
    """
    if not settings.experience_layer_enabled:
        return []

    findings = existing_findings or []
    risk_ids = _extract_risk_ids_from_findings(findings)
    cats = _extract_categories_from_findings(findings)
    items = await list_active_experience_items(db)
    out: list[RiskFinding] = []
    for item in items:
        if item_matches_project(
            item,
            project_type=project_type,
            finding_risk_ids=risk_ids,
            finding_categories=cats,
            document_corpus=document_corpus,
        ):
            out.append(experience_to_finding(item, lang=lang))
    logger.info(
        "Experience layer: %s items scanned, %s matched (project_type=%s)",
        len(items),
        len(out),
        project_type,
    )
    return out


def suggest_experience_id(title: str, category: str | None = None) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", (title or "ITEM").upper()).strip("-")[:40]
    cat = re.sub(r"[^A-Za-z0-9]+", "-", (category or "GEN").upper()).strip("-")[:12]
    return f"EXP-{cat}-{base}"[:120]
