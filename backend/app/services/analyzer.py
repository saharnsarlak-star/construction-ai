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
    document_has_extraction_limitation,
    has_low_extraction_confidence,
    has_usable_text,
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
    topics: list[str] = []

    if sclass == "contractual" or "GENERAL_CONDITIONS" in c or "VOB" in c or "CCDC" in c or "FIDIC" in c:
        topics.extend(["contract_general", "payment", "claims"])
    if "NBR_03" in c or "حریق" in t or "fire" in t:
        topics.append("fire")
    if "NBR_13" in c or "برقی" in t or "electrical" in t:
        topics.append("electrical")
    if "NBR_14" in c or "مکانیک" in t:
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
    if "NBR_12" in c or "HSE" in c or "ایمنی" in t:
        topics.append("safety_site")
    if "NBR_18" in c or "صدا" in t:
        topics.append("acoustic")
    if "FEHREST_ABNIEH" in c or ("فهرست" in t and "ابنیه" in t):
        topics.append("boq_building")
    if "FEHREST_TAASISAT_BARGH" in c:
        topics.append("boq_elec")
    if "FEHREST_TAASISAT_MECHANIC" in c:
        topics.append("boq_mech")
    if "FEHREST" in c and not topics:
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
    Unverifiable standards → ONE consolidated finding.
    """
    if not selected_standards:
        return []

    findings: list[RiskFinding] = []
    technical_corpus = f"{tender_text}\n{standard_text}\n{drawing_text}"
    contract_corpus = tender_text
    unverifiable: list[str] = []

    for item in selected_standards:
        code = item.get("code") or ""
        title = item.get("title") or code
        sclass = item.get("standard_class") or "technical"
        std = get_standard(code)
        if std:
            title = std.title_for(lang.value if hasattr(lang, "value") else str(lang))
        topics = _topics_for_standard(code, title, sclass)
        corpus = contract_corpus if sclass == "contractual" else technical_corpus
        covered = any(_corpus_covers_topic(corpus, topic) for topic in topics)
        if not covered:
            unverifiable.append(title)

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
                    source_excerpt=preview[:500],
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

    # Methodology footer (not a risk card)
    names = "؛ ".join((s.get("title") or s.get("code") or "") for s in selected_standards[:15])
    more = f" (+{len(selected_standards) - 15})" if len(selected_standards) > 15 else ""
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
                LanguageCode.FA: f"{names}{more}",
                LanguageCode.EN: f"{names}{more}",
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
        return apply_composed_risk(
            RiskFinding(
                code=rule.code,
                category=rule.category,
                severity=rule.severity,
                finding_category="risk",
                title=_lang(rule.title, lang),
                description=_lang(rule.description, lang),
                recommendation=_lang(rule.recommendation, lang),
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
        hit = _apply_rule(rule, by_cat=by_cat, corpus=corpus_for_rules, lang=lang, caveat=caveat)
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
