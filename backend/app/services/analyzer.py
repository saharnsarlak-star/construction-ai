from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge.country_profiles import get_country_profile, profile_snapshot
from app.knowledge.document_templates import resolve_document_template
from app.knowledge.prompt_templates import render_prompt_bundle
from app.knowledge.rules_registry import RuleDef, resolve_rules_for_project
from app.knowledge.standards_catalog import get_standard
from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType, RiskSeverity
from app.services.extractor import has_usable_text


@dataclass
class RiskFinding:
    code: str
    category: str
    severity: RiskSeverity
    title: str
    description: str
    recommendation: str
    financial_impact: str | None = None
    schedule_impact: str | None = None
    evidence: str | None = None


TRANSLATIONS: dict[str, dict[LanguageCode, str]] = {
    "summary_template": {
        LanguageCode.FA: "آمادگی اسناد: {score}٪. {high} ریسک بالا، {medium} متوسط، {low} پایین. پروفایل: {profile}. مخاطب: کارفرما.",
        LanguageCode.EN: "Document readiness: {score}%. {high} high, {medium} medium, {low} low risks. Profile: {profile}. Audience: Employer.",
        LanguageCode.DE: "Dokumentenbereitschaft: {score}%. {high} hoch, {medium} mittel, {low} niedrig. Profil: {profile}. Zielgruppe: Auftraggeber.",
        LanguageCode.FR: "Niveau de préparation: {score}%. {high} élevé(s), {medium} moyen(s), {low} faible(s). Profil: {profile}. Public: Maître d'ouvrage.",
    },
}


def _lang(map_: dict[LanguageCode, str], lang: LanguageCode) -> str:
    return map_.get(lang) or map_.get(LanguageCode.EN) or next(iter(map_.values()))


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


_COMPLETE_STD_MARKERS = [
    "shall",
    "must",
    "required",
    "باید",
    "الزام",
    "اجباری",
    "ماده",
    "بند",
    "clause",
    "section",
    "pflicht",
    "obligatoire",
    "norm",
    "استاندارد",
    "specification",
    "مشخصات",
    "VOB",
    "DIN",
    "CCDC",
    "NBC",
]


def _analyze_standard_completeness(
    *,
    lang: LanguageCode,
    standard_docs: list[dict],
    tender_text: str,
) -> list[RiskFinding]:
    if not standard_docs:
        return []

    findings: list[RiskFinding] = []
    incomplete_names: list[str] = []

    for doc in standard_docs:
        text = (doc.get("extracted_text") or "").strip()
        name = doc.get("original_name") or "standard"
        if not has_usable_text(text):
            incomplete_names.append(name)
            continue
        cleaned = re.sub(r"\s+", " ", text)
        marker_hits = sum(1 for m in _COMPLETE_STD_MARKERS if m.lower() in cleaned.lower())
        if len(cleaned) < 500 or marker_hits < 2:
            incomplete_names.append(name)

    if incomplete_names:
        findings.append(
            RiskFinding(
                code="STD-THIN-001",
                category="compliance",
                severity=RiskSeverity.MEDIUM,
                title={
                    LanguageCode.FA: "استانداردهای بارگذاری‌شده ناقص یا کم‌ محتوا به نظر می‌رسند",
                    LanguageCode.EN: "Uploaded standards appear thin or incomplete",
                    LanguageCode.DE: "Hochgeladene Standards wirken dünn/unvollständig",
                    LanguageCode.FR: "Normes téléversées paraissent incomplètes",
                }[lang],
                description={
                    LanguageCode.FA: f"فایل‌های مشکوک: {', '.join(incomplete_names[:8])}",
                    LanguageCode.EN: f"Suspect files: {', '.join(incomplete_names[:8])}",
                    LanguageCode.DE: f"Verdächtige Dateien: {', '.join(incomplete_names[:8])}",
                    LanguageCode.FR: f"Fichiers suspects: {', '.join(incomplete_names[:8])}",
                }[lang],
                recommendation={
                    LanguageCode.FA: "نسخه کامل استاندارد اجباری کشور پروژه را بارگذاری کنید.",
                    LanguageCode.EN: "Upload the full mandatory national standards for the project country.",
                    LanguageCode.DE: "Vollständige verpflichtende Landesstandards hochladen.",
                    LanguageCode.FR: "Téléverser les normes nationales obligatoires complètes.",
                }[lang],
                financial_impact="medium",
                schedule_impact="medium",
                evidence=", ".join(incomplete_names[:8]),
            )
        )
    return findings


def _apply_rule(rule: RuleDef, *, by_cat: dict, corpus: str, lang: LanguageCode) -> RiskFinding | None:
    only_if = (rule.logic_config or {}).get("only_if_category")
    if only_if:
        try:
            needed = only_if if isinstance(only_if, DocumentCategory) else DocumentCategory(str(only_if))
        except ValueError:
            needed = None
        if needed is not None and not by_cat.get(needed):
            # Category absent → skip content checks (covered by a separate optional-missing rule).
            return None

    if rule.requires_category:
        if not by_cat.get(rule.requires_category):
            return RiskFinding(
                code=rule.code,
                category=rule.category,
                severity=rule.severity,
                title=_lang(rule.title, lang),
                description=_lang(rule.description, lang),
                recommendation=_lang(rule.recommendation, lang),
                financial_impact=rule.financial_impact,
                schedule_impact=rule.schedule_impact,
                evidence=None,
            )
        return None

    keywords = rule.keywords_any or []
    if keywords and not _contains_any(corpus, keywords):
        return RiskFinding(
            code=rule.code,
            category=rule.category,
            severity=rule.severity,
            title=_lang(rule.title, lang),
            description=_lang(rule.description, lang),
            recommendation=_lang(rule.recommendation, lang),
            financial_impact=rule.financial_impact,
            schedule_impact=rule.schedule_impact,
            evidence=None,
        )
    return None


def _analyze_selected_standards(
    *,
    lang: LanguageCode,
    selected_standards: list[dict],
    tender_text: str,
    standard_text: str,
    drawing_names: list[str],
) -> list[RiskFinding]:
    """Cross-check selected catalog standards against tender/contract vs technical docs."""
    if not selected_standards:
        return []

    findings: list[RiskFinding] = []
    contract_corpus = tender_text
    technical_corpus = "\n".join([standard_text, tender_text, " ".join(drawing_names)])

    for item in selected_standards:
        code = item.get("code") or ""
        title = item.get("title") or code
        sclass = item.get("standard_class") or "technical"
        std = get_standard(code)
        keywords = list(std.check_keywords) if std else []
        if code:
            keywords.append(code.replace("_", " "))

        if sclass == "contractual":
            target = contract_corpus
            target_label = {
                LanguageCode.FA: "اسناد پیمان/قرارداد",
                LanguageCode.EN: "contract / tender conditions",
                LanguageCode.DE: "Vertrags-/Ausschreibungsunterlagen",
                LanguageCode.FR: "contrat / conditions d'AO",
            }[lang]
        else:
            target = technical_corpus
            target_label = {
                LanguageCode.FA: "نقشه / مشخصات / BoQ / استاندارد بارگذاری‌شده",
                LanguageCode.EN: "drawings / specs / BoQ / uploaded standards",
                LanguageCode.DE: "Pläne / Specs / LV / hochgeladene Standards",
                LanguageCode.FR: "plans / specs / métré / normes téléversées",
            }[lang]

        if keywords and not _contains_any(target, keywords):
            findings.append(
                RiskFinding(
                    code=f"STD-MATCH-{code[:24]}",
                    category="compliance",
                    severity=RiskSeverity.MEDIUM,
                    title={
                        LanguageCode.FA: f"ارجاع ضعیف به استاندارد انتخاب‌شده: {title}",
                        LanguageCode.EN: f"Weak reference to selected standard: {title}",
                        LanguageCode.DE: f"Schwacher Bezug zum gewählten Standard: {title}",
                        LanguageCode.FR: f"Référence faible à la norme sélectionnée : {title}",
                    }[lang],
                    description={
                        LanguageCode.FA: f"استاندارد «{title}» ({sclass}) انتخاب شده ولی در {target_label} نشانه‌ای از ارجاع به آن دیده نشد.",
                        LanguageCode.EN: f"Standard “{title}” ({sclass}) is selected but no clear reference was found in {target_label}.",
                        LanguageCode.DE: f"Standard „{title}“ ({sclass}) gewählt, aber kein klarer Bezug in {target_label}.",
                        LanguageCode.FR: f"Norme « {title} » ({sclass}) sélectionnée, mais pas de référence claire dans {target_label}.",
                    }[lang],
                    recommendation={
                        LanguageCode.FA: "ارجاع صریح به این استاندارد را در اسناد هدف بنویسید یا فایل استاندارد را بارگذاری کنید.",
                        LanguageCode.EN: "Cite this standard explicitly in the target documents, or upload the standard file.",
                        LanguageCode.DE: "Standard in Zieldokumenten ausdrücklich nennen oder Datei hochladen.",
                        LanguageCode.FR: "Citer explicitement cette norme dans les documents cibles, ou téléverser le fichier.",
                    }[lang],
                    financial_impact="medium",
                    schedule_impact="low",
                    evidence=code,
                )
            )

    names = ", ".join((s.get("title") or s.get("code") or "") for s in selected_standards[:8])
    more = f" (+{len(selected_standards) - 8})" if len(selected_standards) > 8 else ""
    findings.append(
        RiskFinding(
            code="STD-SELECT-001",
            category="compliance",
            severity=RiskSeverity.LOW,
            title={
                LanguageCode.FA: "استانداردهای اعمال‌شده در این تحلیل",
                LanguageCode.EN: "Standards applied in this analysis",
                LanguageCode.DE: "In dieser Analyse angewandte Standards",
                LanguageCode.FR: "Normes appliquées dans cette analyse",
            }[lang],
            description={
                LanguageCode.FA: f"انتخاب‌شده: {names}{more}",
                LanguageCode.EN: f"Selected: {names}{more}",
                LanguageCode.DE: f"Ausgewählt: {names}{more}",
                LanguageCode.FR: f"Sélectionnées : {names}{more}",
            }[lang],
            recommendation={
                LanguageCode.FA: "در صورت نیاز چک‌لیست استانداردها را قبل از مناقصه نهایی کنید.",
                LanguageCode.EN: "Finalize the standards checklist before tender issue if needed.",
                LanguageCode.DE: "Standards-Checkliste vor Ausschreibung finalisieren.",
                LanguageCode.FR: "Finaliser la liste des normes avant lancement de l'AO.",
            }[lang],
            financial_impact="low",
            schedule_impact="low",
            evidence=names,
        )
    )
    return findings


def analyze_project_documents(
    *,
    country: CountryCode,
    report_language: LanguageCode,
    documents: list[dict],
    project_type: ProjectType | None = None,
    selected_standards: list[dict] | None = None,
) -> dict:
    """Country-aware rule engine: resolve RuleSet + overrides from knowledge data."""
    lang = report_language
    ptype = project_type or ProjectType.INFRASTRUCTURE
    profile = get_country_profile(country)
    rules = resolve_rules_for_project(
        country=country,
        project_type=ptype,
        ruleset_code=profile.default_ruleset_code,
    )
    selected_standards = selected_standards or []

    by_cat: dict[DocumentCategory, list[dict]] = {c: [] for c in DocumentCategory}
    for doc in documents:
        by_cat[doc["category"]].append(doc)

    tender_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.TENDER])
    standard_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.STANDARD])
    schedule_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.SCHEDULE])
    drawing_names = [d["original_name"] for d in by_cat[DocumentCategory.DRAWING]]

    # Document templates selected for this country (logic/context, not just labels)
    templates = {
        cat.value: resolve_document_template(category=cat, country=country, project_type=ptype).code
        for cat in DocumentCategory
    }

    corpus = "\n".join([tender_text, standard_text, schedule_text, " ".join(drawing_names)])
    # Boost corpus with country-specific framework hints so presence checks are jurisdiction-aware
    hint_blob = " ".join(profile.config.get("contract_keywords_hint") or [])
    corpus_for_rules = corpus  # findings still based on uploaded docs only

    findings: list[RiskFinding] = []

    # Selected catalog standards vs document evidence
    findings.extend(
        _analyze_selected_standards(
            lang=lang,
            selected_standards=selected_standards,
            tender_text=tender_text,
            standard_text=standard_text,
            drawing_names=drawing_names,
        )
    )

    unreadables = [d for d in documents if not has_usable_text(d.get("extracted_text") or "")]
    if unreadables:
        names = ", ".join(d["original_name"] for d in unreadables[:8])
        more = f" (+{len(unreadables) - 8})" if len(unreadables) > 8 else ""
        findings.append(
            RiskFinding(
                code="OCR-001",
                category="process",
                severity=RiskSeverity.HIGH
                if any(d["category"] in {DocumentCategory.TENDER, DocumentCategory.STANDARD} for d in unreadables)
                else RiskSeverity.MEDIUM,
                title={
                    LanguageCode.FA: "متن قابل تحلیل از برخی فایل‌ها استخراج نشد",
                    LanguageCode.EN: "No usable text extracted from some uploaded files",
                    LanguageCode.DE: "Aus einigen Dateien kein nutzbarer Text",
                    LanguageCode.FR: "Aucun texte exploitable extrait de certains fichiers",
                }[lang],
                description={
                    LanguageCode.FA: f"فایل‌های بدون متن: {names}{more}",
                    LanguageCode.EN: f"Files without usable text: {names}{more}",
                    LanguageCode.DE: f"Dateien ohne Text: {names}{more}",
                    LanguageCode.FR: f"Fichiers sans texte: {names}{more}",
                }[lang],
                recommendation={
                    LanguageCode.FA: "نسخه متنی/Word بارگذاری کنید یا OCR را فعال کنید.",
                    LanguageCode.EN: "Upload text/Word versions or enable OCR.",
                    LanguageCode.DE: "Text-/Word-Version hochladen oder OCR aktivieren.",
                    LanguageCode.FR: "Charger une version texte/Word ou activer l'OCR.",
                }[lang],
                financial_impact="high",
                schedule_impact="medium",
                evidence=names,
            )
        )

    findings.extend(
        _analyze_standard_completeness(
            lang=lang,
            standard_docs=by_cat[DocumentCategory.STANDARD],
            tender_text=tender_text,
        )
    )

    for rule in rules:
        if rule.code == "STD-001" and selected_standards:
            # Catalog selection covers the "no standards pack" gap.
            continue
        hit = _apply_rule(rule, by_cat=by_cat, corpus=corpus_for_rules, lang=lang)
        if hit:
            # annotate evidence with resolved jurisdiction when useful
            if rule.override_country and not hit.evidence:
                hit.evidence = f"ruleset={profile.default_ruleset_code}; override={rule.override_country.value}"
            findings.append(hit)

    # Cross-doc schedule heuristic
    if by_cat[DocumentCategory.TENDER] and by_cat[DocumentCategory.SCHEDULE]:
        tender_has_duration = _contains_any(
            tender_text,
            ["مدت", "ماه", "روز", "duration", "weeks", "months", "Fertigstellung", "Bauzeit", "completion"],
        )
        schedule_has_dates = bool(
            re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", schedule_text)
        )
        if tender_has_duration and not schedule_has_dates:
            findings.append(
                RiskFinding(
                    code="XR-TIME-001",
                    category="schedule",
                    severity=RiskSeverity.MEDIUM,
                    title={
                        LanguageCode.FA: "عدم هم‌خوانی مدت پیمان و جزئیات برنامه",
                        LanguageCode.EN: "Mismatch between contract duration and schedule detail",
                        LanguageCode.DE: "Widerspruch Vertragslaufzeit / Terminplan-Detail",
                        LanguageCode.FR: "Écart durée du marché / détail du planning",
                    }[lang],
                    description={
                        LanguageCode.FA: "مدت در اسناد هست اما برنامه جزئیات تاریخ کافی ندارد.",
                        LanguageCode.EN: "Duration exists in tender docs but schedule lacks date detail.",
                        LanguageCode.DE: "Laufzeit genannt, Terminplan ohne ausreichende Daten.",
                        LanguageCode.FR: "Durée citée mais planning sans dates suffisantes.",
                    }[lang],
                    recommendation={
                        LanguageCode.FA: "برنامه مبنا را با مدت قراردادی هم‌راستا کنید.",
                        LanguageCode.EN: "Align baseline schedule with contractual duration.",
                        LanguageCode.DE: "Basisterminplan mit Vertragslaufzeit abstimmen.",
                        LanguageCode.FR: "Aligner le planning avec la durée contractuelle.",
                    }[lang],
                    financial_impact="medium",
                    schedule_impact="high",
                )
            )

    if standard_text.strip() and tender_text.strip():
        std_keywords = set(re.findall(r"[\w\u0600-\u06FF]{5,}", standard_text.lower()))
        tender_keywords = set(re.findall(r"[\w\u0600-\u06FF]{5,}", tender_text.lower()))
        distinctive = [w for w in list(std_keywords)[:400] if w not in tender_keywords]
        if len(distinctive) > 80:
            findings.append(
                RiskFinding(
                    code="STD-ALIGN-001",
                    category="compliance",
                    severity=RiskSeverity.MEDIUM,
                    title={
                        LanguageCode.FA: "فاصله بین استاندارد و اسناد مناقصه",
                        LanguageCode.EN: "Gap between standards and tender documents",
                        LanguageCode.DE: "Lücke zwischen Standards und Ausschreibung",
                        LanguageCode.FR: "Écart entre normes et documents d'AO",
                    }[lang],
                    description={
                        LanguageCode.FA: "بخش زیادی از واژگان استاندارد در مناقصه دیده نشد.",
                        LanguageCode.EN: "Much standards vocabulary is absent from tender text.",
                        LanguageCode.DE: "Viele Standardbegriffe fehlen in der Ausschreibung.",
                        LanguageCode.FR: "Beaucoup de vocabulaire normatif est absent de l'AO.",
                    }[lang],
                    recommendation={
                        LanguageCode.FA: f"الزامات استاندارد را با چارچوب {profile.primary_standards_system} به شرایط خصوصی منتقل کنید.",
                        LanguageCode.EN: f"Transfer mandatory clauses into particular conditions using {profile.primary_standards_system}.",
                        LanguageCode.DE: f"Pflichtklauseln über {profile.primary_standards_system} in besondere Bedingungen überführen.",
                        LanguageCode.FR: f"Reprendre les clauses obligatoires via {profile.primary_standards_system}.",
                    }[lang],
                    financial_impact="medium",
                    schedule_impact="medium",
                    evidence=", ".join(distinctive[:12]),
                )
            )

    if not by_cat[DocumentCategory.STANDARD] and not selected_standards:
        findings.append(
            RiskFinding(
                code="COUNTRY-STD-001",
                category="compliance",
                severity=RiskSeverity.MEDIUM,
                title={
                    LanguageCode.FA: f"هیچ استانداردی برای {country.value} انتخاب یا بارگذاری نشده",
                    LanguageCode.EN: f"No standards selected or uploaded for {country.value}",
                    LanguageCode.DE: f"Keine Standards gewählt/hochgeladen für {country.value}",
                    LanguageCode.FR: f"Aucune norme sélectionnée/téléversée pour {country.value}",
                }[lang],
                description={
                    LanguageCode.FA: f"پروفایل {profile.code} به سیستم {profile.primary_standards_system} وابسته است. از چک‌لیست استانداردها انتخاب کنید یا فایل سفارشی بارگذاری کنید.",
                    LanguageCode.EN: f"Profile {profile.code} depends on {profile.primary_standards_system}. Select from the standards checklist or upload a custom file.",
                    LanguageCode.DE: f"Profil {profile.code} hängt von {profile.primary_standards_system} ab.",
                    LanguageCode.FR: f"Le profil {profile.code} dépend de {profile.primary_standards_system}.",
                }[lang],
                recommendation={
                    LanguageCode.FA: "استانداردهای پیشنهادی کشور را تیک بزنید یا فایل استاندارد بارگذاری کنید.",
                    LanguageCode.EN: "Tick recommended country standards or upload a standards file.",
                    LanguageCode.DE: "Empfohlene Landesstandards anhaken oder Datei hochladen.",
                    LanguageCode.FR: "Cocher les normes recommandées ou téléverser un fichier.",
                }[lang],
                financial_impact="high",
                schedule_impact="medium",
            )
        )

    if not documents:
        findings.append(
            RiskFinding(
                code="EMPTY-001",
                category="process",
                severity=RiskSeverity.HIGH,
                title={
                    LanguageCode.FA: "هیچ سندی بارگذاری نشده",
                    LanguageCode.EN: "No documents uploaded",
                    LanguageCode.DE: "Keine Dokumente hochgeladen",
                    LanguageCode.FR: "Aucun document téléversé",
                }[lang],
                description={
                    LanguageCode.FA: "برای گزارش ریسک حداقل اسناد مناقصه کافی است؛ نقشه، زمان‌بندی و استاندارد اختیاری‌اند ولی کیفیت را بالا می‌برند.",
                    LanguageCode.EN: "Tender documents are enough to run analysis; drawings, schedule, and standards are optional but improve quality.",
                    LanguageCode.DE: "Ausschreibungsunterlagen reichen; Pläne, Terminplan und Standards sind optional.",
                    LanguageCode.FR: "Les documents d'AO suffisent; plans, planning et normes sont optionnels.",
                }[lang],
                recommendation={
                    LanguageCode.FA: "حداقل اسناد مناقصه را بارگذاری کنید. برنامه زمان‌بندی در صورت نبود مانع تحلیل نیست.",
                    LanguageCode.EN: "Upload at least tender docs. Missing schedule does not block analysis.",
                    LanguageCode.DE: "Mindestens Ausschreibung hochladen. Fehlender Terminplan blockiert die Analyse nicht.",
                    LanguageCode.FR: "Téléverser au moins l'AO. L'absence de planning ne bloque pas l'analyse.",
                }[lang],
                financial_impact="high",
                schedule_impact="high",
            )
        )

    # Prepare country prompt bundle for future LLM layer (stored in analysis metadata)
    prompt_bundle = render_prompt_bundle(
        code="ANALYZE_RESPONSIBILITY_CLAUSES",
        country=country,
        project_type=ptype,
        extracted_text_excerpt=tender_text or hint_blob,
    )

    high = sum(1 for f in findings if f.severity == RiskSeverity.HIGH)
    medium = sum(1 for f in findings if f.severity == RiskSeverity.MEDIUM)
    low = sum(1 for f in findings if f.severity == RiskSeverity.LOW)
    penalty = high * 12 + medium * 6 + low * 2
    score = max(0, min(100, 100 - penalty))

    summary = TRANSLATIONS["summary_template"][lang].format(
        score=score,
        high=high,
        medium=medium,
        low=low,
        profile=profile.code,
    )

    return {
        "summary": summary,
        "readiness_score": score,
        "counts": {"high": high, "medium": medium, "low": low, "total": len(findings)},
        "findings": findings,
        "engine": {
            "country_profile": profile_snapshot(country, ptype),
            "ruleset": profile.default_ruleset_code,
            "resolved_rules": [r.code for r in rules],
            "document_templates": templates,
            "selected_standards": [s.get("code") for s in selected_standards],
            "prompt_bundle": {
                "template_code": prompt_bundle["template_code"],
                "resolved_country_scope": prompt_bundle["resolved_country_scope"],
                "context_pack": prompt_bundle["context_pack"],
            },
        },
    }
