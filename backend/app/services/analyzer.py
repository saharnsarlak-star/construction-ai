from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import CountryCode, DocumentCategory, LanguageCode, RiskSeverity
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
        LanguageCode.FA: "آمادگی اسناد: {score}٪. {high} ریسک بالا، {medium} متوسط، {low} پایین. مخاطب گزارش: کارفرما.",
        LanguageCode.EN: "Document readiness: {score}%. {high} high, {medium} medium, {low} low risks. Audience: Employer.",
        LanguageCode.DE: "Dokumentenbereitschaft: {score}%. {high} hoch, {medium} mittel, {low} niedrig. Zielgruppe: Auftraggeber.",
        LanguageCode.FR: "Niveau de préparation des documents: {score}%. {high} élevé(s), {medium} moyen(s), {low} faible(s). Public: Maître d'ouvrage.",
    },
}


IRAN_EMPLOYER_CHECKS = [
    {
        "code": "IR-SCOPE-001",
        "category": "scope",
        "severity": RiskSeverity.HIGH,
        "keywords_any": ["شرح کار", "محدوده کار", "scope", "کارهای موضوع پیمان"],
        "missing_title": {
            LanguageCode.FA: "شرح کار / محدوده کار مبهم یا ناقص",
            LanguageCode.EN: "Ambiguous or incomplete scope of work",
            LanguageCode.DE: "Unklarer oder unvollständiger Leistungsumfang",
            LanguageCode.FR: "Périmètre des travaux ambigu ou incomplet",
        },
        "missing_desc": {
            LanguageCode.FA: "بدون شرح کار شفاف، پیمانکار می‌تواند کارهای اضافی و ادعاهای مالی طرح کند.",
            LanguageCode.EN: "Without a clear scope, the contractor may claim extras and variations.",
            LanguageCode.DE: "Ohne klaren Leistungsumfang drohen Nachträge und Mehrkosten.",
            LanguageCode.FR: "Sans périmètre clair, l'entreprise peut réclamer des travaux supplémentaires.",
        },
        "recommendation": {
            LanguageCode.FA: "شرح کار تفصیلی، مرز مسئولیت‌ها و اقلام خارج از محدوده را قبل از مناقصه تکمیل کنید.",
            LanguageCode.EN: "Complete a detailed scope, responsibility boundaries, and exclusions before tender.",
            LanguageCode.DE: "Detaillierten Leistungsumfang, Verantwortlichkeiten und Ausschlüsse vor der Ausschreibung ergänzen.",
            LanguageCode.FR: "Compléter le périmètre détaillé, les responsabilités et les exclusions avant l'appel d'offres.",
        },
        "financial_impact": "high",
        "schedule_impact": "medium",
    },
    {
        "code": "IR-BOQ-001",
        "category": "financial",
        "severity": RiskSeverity.HIGH,
        "keywords_any": ["فهرست بها", "متره", "برآورد", "boq", "bill of quantities", "جدول مقادیر"],
        "missing_title": {
            LanguageCode.FA: "فهرست مقادیر / برآورد ناقص یا غایب",
            LanguageCode.EN: "Missing or incomplete bill of quantities / estimate",
            LanguageCode.DE: "Fehlendes oder unvollständiges Leistungsverzeichnis",
            LanguageCode.FR: "DPGF / métré manquant ou incomplet",
        },
        "missing_desc": {
            LanguageCode.FA: "نقص در مقادیر مبنای ادعاهای افزایش مبلغ و اختلاف پرداخت است.",
            LanguageCode.EN: "Quantity gaps commonly drive contract value claims and payment disputes.",
            LanguageCode.DE: "Mengenlücken führen häufig zu Nachträgen und Zahlungsstreitigkeiten.",
            LanguageCode.FR: "Les écarts de quantités génèrent souvent des réclamations financières.",
        },
        "recommendation": {
            LanguageCode.FA: "BoQ را با نقشه‌ها و مشخصات فنی هم‌راستا و کنترل متقابل کنید.",
            LanguageCode.EN: "Cross-check BoQ against drawings and specifications.",
            LanguageCode.DE: "LV mit Plänen und Spezifikationen abgleichen.",
            LanguageCode.FR: "Recouper le métré avec plans et spécifications.",
        },
        "financial_impact": "high",
        "schedule_impact": "low",
    },
    {
        "code": "IR-TIME-001",
        "category": "schedule",
        "severity": RiskSeverity.HIGH,
        "keywords_any": ["برنامه زمان", "مدت پیمان", "تأخیر", "schedule", "milestone", "زمان‌بندی"],
        "missing_title": {
            LanguageCode.FA: "برنامه زمان‌بندی یا مدت پیمان ناکافی",
            LanguageCode.EN: "Insufficient schedule or contract duration definition",
            LanguageCode.DE: "Unzureichende Terminplanung oder Vertragslaufzeit",
            LanguageCode.FR: "Planning ou durée du marché insuffisamment défini",
        },
        "missing_desc": {
            LanguageCode.FA: "بدون مایلستون و مسیر بحرانی، تأخیرات و جریمه‌ها قابل دفاع نیستند.",
            LanguageCode.EN: "Without milestones and critical path, delay liability becomes contested.",
            LanguageCode.DE: "Ohne Meilensteine und kritischen Pfad sind Verzugsfolgen streitig.",
            LanguageCode.FR: "Sans jalons et chemin critique, les retards deviennent contestables.",
        },
        "recommendation": {
            LanguageCode.FA: "برنامه زمان‌بندی مبنا، مایلستون‌های پرداخت و شرایط تمدید مدت را صریح کنید.",
            LanguageCode.EN: "Define baseline schedule, payment milestones, and extension-of-time rules.",
            LanguageCode.DE: "Basisterminplan, Zahlungsmeilensteine und Bauzeitverlängerung klar festlegen.",
            LanguageCode.FR: "Définir le planning de référence, jalons de paiement et règles de prolongation.",
        },
        "financial_impact": "medium",
        "schedule_impact": "high",
    },
    {
        "code": "IR-CLAIM-001",
        "category": "claims",
        "severity": RiskSeverity.MEDIUM,
        "keywords_any": ["ادعا", "claim", "تغییر مقادیر", "دستور کار", "کارهای اضافی", "variation"],
        "missing_title": {
            LanguageCode.FA: "مکانیسم ادعا / کارهای اضافی تعریف نشده",
            LanguageCode.EN: "Claim / variation mechanism not defined",
            LanguageCode.DE: "Nachtrags-/Claim-Mechanismus nicht definiert",
            LanguageCode.FR: "Mécanisme de réclamation / avenant non défini",
        },
        "missing_desc": {
            LanguageCode.FA: "نبود فرآیند شفاف تغییر کار، بار مالی پیش‌بینی‌نشده برای کارفرما ایجاد می‌کند.",
            LanguageCode.EN: "Unclear variation process creates uncontrolled employer cost exposure.",
            LanguageCode.DE: "Unklarer Nachtragsprozess erzeugt unkontrollierte Auftraggeberkosten.",
            LanguageCode.FR: "Un processus d'avenant flou expose le maître d'ouvrage à des surcoûts.",
        },
        "recommendation": {
            LanguageCode.FA: "فرآیند ابلاغ، قیمت‌گذاری و سقف تغییرات را در شرایط خصوصی قید کنید.",
            LanguageCode.EN: "Specify notice, pricing, and caps for variations in particular conditions.",
            LanguageCode.DE: "Anzeige, Preisbildung und Obergrenzen für Nachträge in den besonderen Bedingungen regeln.",
            LanguageCode.FR: "Préciser notification, valorisation et plafonds des avenants dans les conditions particulières.",
        },
        "financial_impact": "high",
        "schedule_impact": "medium",
    },
    {
        "code": "IR-ADJ-001",
        "category": "financial",
        "severity": RiskSeverity.MEDIUM,
        "keywords_any": ["تعدیل", "تورم", "تعدیل آحاد بها", "price adjustment", "escalation"],
        "missing_title": {
            LanguageCode.FA: "شرایط تعدیل قیمت شفاف نیست",
            LanguageCode.EN: "Price adjustment / escalation terms unclear",
            LanguageCode.DE: "Preisgleitklausel unklar",
            LanguageCode.FR: "Clause de révision des prix peu claire",
        },
        "missing_desc": {
            LanguageCode.FA: "در پروژه‌های ایران، ابهام تعدیل یکی از منابع اصلی اختلاف مالی است.",
            LanguageCode.EN: "In Iranian projects, unclear escalation is a major source of payment disputes.",
            LanguageCode.DE: "Unklare Preisgleitung ist in iranischen Projekten eine Hauptrisikoquelle.",
            LanguageCode.FR: "En Iran, l'ambiguïté sur la révision des prix est une source majeure de litiges.",
        },
        "recommendation": {
            LanguageCode.FA: "مبنای شاخص، دوره محاسبه و شمول/عدم‌شمول تعدیل را صریح بنویسید.",
            LanguageCode.EN: "State index basis, calculation period, and what is included/excluded.",
            LanguageCode.DE: "Indexbasis, Berechnungszeitraum sowie Ein-/Ausschlüsse klar festlegen.",
            LanguageCode.FR: "Préciser l'indice, la période de calcul et les inclusions/exclusions.",
        },
        "financial_impact": "high",
        "schedule_impact": "low",
    },
    {
        "code": "IR-DRAW-001",
        "category": "technical",
        "severity": RiskSeverity.HIGH,
        "requires_category": DocumentCategory.DRAWING,
        "missing_title": {
            LanguageCode.FA: "نقشه‌های پروژه بارگذاری نشده",
            LanguageCode.EN: "Project drawings not uploaded",
            LanguageCode.DE: "Projektpläne nicht hochgeladen",
            LanguageCode.FR: "Plans du projet non téléversés",
        },
        "missing_desc": {
            LanguageCode.FA: "بدون نقشه، تعارض با متره و مشخصات فنی دیر کشف می‌شود و بار مالی دارد.",
            LanguageCode.EN: "Without drawings, conflicts with BoQ/specs are found late and become costly.",
            LanguageCode.DE: "Ohne Pläne werden Konflikte mit LV/Spezifikation spät und teuer erkannt.",
            LanguageCode.FR: "Sans plans, les conflits métré/specs apparaissent tard et coûtent cher.",
        },
        "recommendation": {
            LanguageCode.FA: "بسته نقشه‌های مصوب را قبل از مناقصه کامل بارگذاری و نسخه‌گذاری کنید.",
            LanguageCode.EN: "Upload and version-control the approved drawing package before tender.",
            LanguageCode.DE: "Genehmigtes Plansatz vor Ausschreibung vollständig hochladen und versionieren.",
            LanguageCode.FR: "Téléverser et versionner le jeu de plans approuvé avant l'AO.",
        },
        "financial_impact": "high",
        "schedule_impact": "high",
    },
    {
        "code": "IR-STD-001",
        "category": "compliance",
        "severity": RiskSeverity.HIGH,
        "requires_category": DocumentCategory.STANDARD,
        "missing_title": {
            LanguageCode.FA: "هیچ استاندارد مرجعی برای پروژه انتخاب/بارگذاری نشده",
            LanguageCode.EN: "No reference standards uploaded for the project",
            LanguageCode.DE: "Keine Referenzstandards für das Projekt hochgeladen",
            LanguageCode.FR: "Aucune norme de référence téléversée pour le projet",
        },
        "missing_desc": {
            LanguageCode.FA: "بدون استاندارد مبنا، انطباق منطقه‌ای و دفاع حقوقی کارفرما ضعیف می‌شود.",
            LanguageCode.EN: "Without baseline standards, regional compliance and employer defense weaken.",
            LanguageCode.DE: "Ohne Basisstandards ist die regionale Compliance und Auftraggeberposition schwach.",
            LanguageCode.FR: "Sans normes de référence, la conformité régionale et la position du MOA s'affaiblissent.",
        },
        "recommendation": {
            LanguageCode.FA: "استانداردهای اجباری ایران (و داخلی سازمان) را در کتابخانه پروژه بارگذاری کنید.",
            LanguageCode.EN: "Upload mandatory Iranian (and internal) standards into the project library.",
            LanguageCode.DE: "Verpflichtende iranische (und interne) Standards in die Projektbibliothek laden.",
            LanguageCode.FR: "Téléverser les normes iraniennes (et internes) obligatoires dans la bibliothèque.",
        },
        "financial_impact": "medium",
        "schedule_impact": "medium",
    },
    {
        "code": "IR-PAY-001",
        "category": "financial",
        "severity": RiskSeverity.MEDIUM,
        "keywords_any": ["پرداخت", "صورت وضعیت", "پیش پرداخت", "ضمانت", "payment", "retention", "ضمانت‌نامه"],
        "missing_title": {
            LanguageCode.FA: "شرایط پرداخت و ضمانت‌ها ناقص به نظر می‌رسد",
            LanguageCode.EN: "Payment and security terms appear incomplete",
            LanguageCode.DE: "Zahlungs- und Sicherheitsbedingungen wirken unvollständig",
            LanguageCode.FR: "Conditions de paiement et garanties semblent incomplètes",
        },
        "missing_desc": {
            LanguageCode.FA: "ابهام در پرداخت/ضمانت‌نامه جریان نقدی و اختلافات مالی می‌سازد.",
            LanguageCode.EN: "Ambiguity in payment/securities creates cash-flow and dispute risk.",
            LanguageCode.DE: "Unklare Zahlungen/Sicherheiten erzeugen Cashflow- und Streitrisiko.",
            LanguageCode.FR: "L'ambiguïté paiement/garanties crée un risque de trésorerie et de litige.",
        },
        "recommendation": {
            LanguageCode.FA: "نسبت پیش‌پرداخت، کسور وجه الضمان، مهلت رسیدگی صورت‌وضعیت را شفاف کنید.",
            LanguageCode.EN: "Clarify advance payment, retention, and interim payment review periods.",
            LanguageCode.DE: "Abschlag, Sicherheitseinbehalt und Prüffristen klar regeln.",
            LanguageCode.FR: "Clarifier avance, retenue de garantie et délais de visa des situations.",
        },
        "financial_impact": "high",
        "schedule_impact": "low",
    },
]


def _lang(map_: dict[LanguageCode, str], lang: LanguageCode) -> str:
    return map_.get(lang) or map_.get(LanguageCode.EN) or next(iter(map_.values()))


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def _snippet(text: str, keyword: str, radius: int = 90) -> str | None:
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return None
    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword) + radius)
    return text[start:end].replace("\n", " ").strip()


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
]


def _analyze_standard_completeness(
    *,
    lang: LanguageCode,
    standard_docs: list[dict],
    tender_text: str,
) -> list[RiskFinding]:
    """Flag incomplete/thin standards and weak transfer into tender docs."""
    if not standard_docs:
        return []

    findings: list[RiskFinding] = []
    incomplete_names: list[str] = []
    complete_count = 0

    for doc in standard_docs:
        text = (doc.get("extracted_text") or "").strip()
        name = doc.get("original_name") or "standard"
        if not has_usable_text(text):
            incomplete_names.append(name)
            continue

        cleaned = re.sub(r"\s+", " ", text)
        marker_hits = sum(1 for m in _COMPLETE_STD_MARKERS if m.lower() in cleaned.lower())
        # Thin file = short body or almost no requirement-like markers
        if len(cleaned) < 500 or marker_hits < 2:
            incomplete_names.append(name)
        else:
            complete_count += 1

    if incomplete_names:
        findings.append(
            RiskFinding(
                code="STD-INCOMPLETE-001",
                category="compliance",
                severity=RiskSeverity.HIGH if complete_count == 0 else RiskSeverity.MEDIUM,
                title={
                    LanguageCode.FA: "استاندارد ناقص یا کم‌محتوا تشخیص داده شد",
                    LanguageCode.EN: "Incomplete or thin standard document detected",
                    LanguageCode.DE: "Unvollständiger oder inhaltlich dünner Standard erkannt",
                    LanguageCode.FR: "Norme incomplète ou trop sommaire détectée",
                }[lang],
                description={
                    LanguageCode.FA: (
                        "برخی استانداردها متن الزام‌آور کافی ندارند (کوتاه، اسکن بدون متن، یا بدون بندهای اجباری). "
                        f"موارد: {', '.join(incomplete_names[:6])}"
                    ),
                    LanguageCode.EN: (
                        "Some standards lack enforceable content (too short, unscanned text, or few mandatory clauses). "
                        f"Items: {', '.join(incomplete_names[:6])}"
                    ),
                    LanguageCode.DE: (
                        "Einige Standards haben zu wenig verbindlichen Inhalt. "
                        f"Dateien: {', '.join(incomplete_names[:6])}"
                    ),
                    LanguageCode.FR: (
                        "Certaines normes manquent de contenu opposable. "
                        f"Fichiers: {', '.join(incomplete_names[:6])}"
                    ),
                }[lang],
                recommendation={
                    LanguageCode.FA: "نسخه کامل استاندارد (PDF متنی یا Word) را جایگزین کنید؛ نسخه ناقص مبنای دفاع حقوقی کارفرما نیست.",
                    LanguageCode.EN: "Replace with the full textual standard; incomplete versions weaken employer defensibility.",
                    LanguageCode.DE: "Vollständigen Textstandard hochladen; unvollständige Versionen schwächen die Auftraggeberposition.",
                    LanguageCode.FR: "Remplacer par la norme complète textuelle; une version partielle affaiblit la position du MOA.",
                }[lang],
                financial_impact="high",
                schedule_impact="medium",
                evidence=", ".join(incomplete_names[:8]),
            )
        )

    # If we have at least one usable standard, check whether tender absorbs key obligation words
    usable_std = "\n".join(
        (d.get("extracted_text") or "")
        for d in standard_docs
        if has_usable_text(d.get("extracted_text") or "")
    )
    if usable_std and tender_text.strip() and has_usable_text(tender_text):
        std_obligations = [
            m for m in _COMPLETE_STD_MARKERS if m.lower() in usable_std.lower()
        ]
        missing_in_tender = [m for m in std_obligations if m.lower() not in tender_text.lower()]
        # Only flag when standards clearly use obligation language that tender lacks entirely
        if len(std_obligations) >= 3 and len(missing_in_tender) >= 3:
            findings.append(
                RiskFinding(
                    code="STD-TRANSFER-001",
                    category="compliance",
                    severity=RiskSeverity.MEDIUM,
                    title={
                        LanguageCode.FA: "الزامات استاندارد به اسناد مناقصه منتقل نشده‌اند",
                        LanguageCode.EN: "Standard obligations not reflected in tender documents",
                        LanguageCode.DE: "Standardpflichten nicht in Ausschreibungsunterlagen abgebildet",
                        LanguageCode.FR: "Obligations normatives non reprises dans le dossier d'AO",
                    }[lang],
                    description={
                        LanguageCode.FA: "زبان الزام‌آور استاندارد در اسناد مناقصه کم‌رنگ است؛ ریسک عدم‌انطباق و ادعای پیمانکار بالا می‌رود.",
                        LanguageCode.EN: "Mandatory wording from standards is weak in tender docs; non-compliance and contractor claims rise.",
                        LanguageCode.DE: "Verbindliche Standardformulierungen fehlen in den Ausschreibungsunterlagen.",
                        LanguageCode.FR: "Le vocabulaire obligatoire des normes est peu présent dans l'AO.",
                    }[lang],
                    recommendation={
                        LanguageCode.FA: "بندهای اجباری استاندارد کامل را در شرایط خصوصی و مشخصات فنی صریح کنید.",
                        LanguageCode.EN: "Explicitly embed mandatory clauses from the complete standard into particular conditions and specs.",
                        LanguageCode.DE: "Verpflichtende Klauseln des vollständigen Standards in besondere Bedingungen/Spezifikationen übernehmen.",
                        LanguageCode.FR: "Reprendre explicitement les clauses obligatoires de la norme complète dans les CCAP/CCTP.",
                    }[lang],
                    financial_impact="medium",
                    schedule_impact="medium",
                    evidence=", ".join(missing_in_tender[:8]),
                )
            )

    return findings


def analyze_project_documents(
    *,
    country: CountryCode,
    report_language: LanguageCode,
    documents: list[dict],
) -> dict:
    """Rule-based MVP analyzer oriented to employer risks.

    documents: [{category, original_name, extracted_text}]
    """
    lang = report_language
    by_cat: dict[DocumentCategory, list[dict]] = {c: [] for c in DocumentCategory}
    for doc in documents:
        by_cat[doc["category"]].append(doc)

    tender_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.TENDER])
    standard_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.STANDARD])
    schedule_text = "\n".join((d.get("extracted_text") or "") for d in by_cat[DocumentCategory.SCHEDULE])
    drawing_names = [d["original_name"] for d in by_cat[DocumentCategory.DRAWING]]

    corpus = "\n".join(
        [
            tender_text,
            standard_text,
            schedule_text,
            " ".join(drawing_names),
        ]
    )

    findings: list[RiskFinding] = []

    # Unreadable / scanned docs without usable OCR text
    unreadables = [
        d
        for d in documents
        if not has_usable_text(d.get("extracted_text") or "")
    ]
    if unreadables:
        names = ", ".join(d["original_name"] for d in unreadables[:8])
        more = f" (+{len(unreadables) - 8})" if len(unreadables) > 8 else ""
        findings.append(
            RiskFinding(
                code="OCR-001",
                category="process",
                severity=RiskSeverity.HIGH if any(
                    d["category"] in {DocumentCategory.TENDER, DocumentCategory.STANDARD}
                    for d in unreadables
                )
                else RiskSeverity.MEDIUM,
                title={
                    LanguageCode.FA: "متن قابل تحلیل از برخی فایل‌ها استخراج نشد",
                    LanguageCode.EN: "No usable text extracted from some uploaded files",
                    LanguageCode.DE: "Aus einigen Dateien konnte kein nutzbarer Text extrahiert werden",
                    LanguageCode.FR: "Aucun texte exploitable extrait de certains fichiers",
                }[lang],
                description={
                    LanguageCode.FA: f"فایل‌های بدون متن قابل استفاده: {names}{more}. احتمالاً اسکن تصویری یا OCR ناموفق است.",
                    LanguageCode.EN: f"Files without usable text: {names}{more}. Likely scanned images or failed OCR.",
                    LanguageCode.DE: f"Dateien ohne nutzbaren Text: {names}{more}. Wahrscheinlich Scan/OCR-Problem.",
                    LanguageCode.FR: f"Fichiers sans texte exploitable: {names}{more}. Probable scan ou OCR échoué.",
                }[lang],
                recommendation={
                    LanguageCode.FA: "نسخه متنی/Word بارگذاری کنید یا از OCR سیستم استفاده کنید و دوباره تحلیل کنید.",
                    LanguageCode.EN: "Upload a text/Word version or ensure OCR is installed, then re-analyze.",
                    LanguageCode.DE: "Text-/Word-Version hochladen oder OCR sicherstellen und erneut analysieren.",
                    LanguageCode.FR: "Charger une version texte/Word ou activer l'OCR, puis relancer l'analyse.",
                }[lang],
                financial_impact="high",
                schedule_impact="medium",
                evidence=names,
            )
        )

    # Incomplete vs complete standards heuristics
    findings.extend(
        _analyze_standard_completeness(
            lang=lang,
            standard_docs=by_cat[DocumentCategory.STANDARD],
            tender_text=tender_text,
        )
    )

    # Category presence checks + keyword checks (Iran-first profile; shared baseline for others)
    checks = IRAN_EMPLOYER_CHECKS
    for check in checks:
        req_cat = check.get("requires_category")
        if req_cat:
            if not by_cat.get(req_cat):
                findings.append(
                    RiskFinding(
                        code=check["code"],
                        category=check["category"],
                        severity=check["severity"],
                        title=_lang(check["missing_title"], lang),
                        description=_lang(check["missing_desc"], lang),
                        recommendation=_lang(check["recommendation"], lang),
                        financial_impact=check.get("financial_impact"),
                        schedule_impact=check.get("schedule_impact"),
                        evidence=None,
                    )
                )
            continue

        keywords = check.get("keywords_any") or []
        if keywords and not _contains_any(corpus, keywords):
            findings.append(
                RiskFinding(
                    code=check["code"],
                    category=check["category"],
                    severity=check["severity"],
                    title=_lang(check["missing_title"], lang),
                    description=_lang(check["missing_desc"], lang),
                    recommendation=_lang(check["recommendation"], lang),
                    financial_impact=check.get("financial_impact"),
                    schedule_impact=check.get("schedule_impact"),
                    evidence=None,
                )
            )

    # Cross-document consistency heuristics
    if by_cat[DocumentCategory.TENDER] and by_cat[DocumentCategory.SCHEDULE]:
        tender_has_duration = _contains_any(tender_text, ["مدت", "ماه", "روز", "duration", "weeks", "months"])
        schedule_has_dates = bool(re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", schedule_text))
        if tender_has_duration and not schedule_has_dates:
            findings.append(
                RiskFinding(
                    code="XR-TIME-001",
                    category="schedule",
                    severity=RiskSeverity.MEDIUM,
                    title={
                        LanguageCode.FA: "عدم هم‌خوانی ظاهری مدت پیمان و برنامه زمان‌بندی",
                        LanguageCode.EN: "Apparent mismatch between contract duration and schedule detail",
                        LanguageCode.DE: "Scheinbarer Widerspruch zwischen Vertragslaufzeit und Terminplan",
                        LanguageCode.FR: "Décalage apparent entre durée du marché et détail du planning",
                    }[lang],
                    description={
                        LanguageCode.FA: "در اسناد مدت ذکر شده اما برنامه زمان‌بندی جزئیات تاریخ/مایلستون کافی ندارد.",
                        LanguageCode.EN: "Duration is mentioned in tender docs but schedule lacks date/milestone detail.",
                        LanguageCode.DE: "Laufzeit ist genannt, aber der Terminplan hat zu wenig Datums-/Meilenstein-Details.",
                        LanguageCode.FR: "La durée est citée mais le planning manque de dates/jalons.",
                    }[lang],
                    recommendation={
                        LanguageCode.FA: "برنامه مبنا را با مدت پیمان و مایلستون‌های قراردادی هم‌راستا کنید.",
                        LanguageCode.EN: "Align baseline schedule with contractual duration and milestones.",
                        LanguageCode.DE: "Basisterminplan mit Vertragslaufzeit und Meilensteinen abstimmen.",
                        LanguageCode.FR: "Aligner le planning de référence avec la durée et les jalons contractuels.",
                    }[lang],
                    financial_impact="medium",
                    schedule_impact="high",
                )
            )

    # Standards vs tender keyword overlap (lightweight MVP signal)
    if standard_text.strip() and tender_text.strip():
        std_keywords = set(re.findall(r"[\w\u0600-\u06FF]{5,}", standard_text.lower()))
        tender_keywords = set(re.findall(r"[\w\u0600-\u06FF]{5,}", tender_text.lower()))
        # Focus on requirement-ish tokens
        requirement_markers = [
            "باید",
            "الزام",
            "اجباری",
            "shall",
            "must",
            "pflicht",
            "obligatoire",
            "required",
        ]
        marked = [w for w in std_keywords if any(m in w for m in requirement_markers) or w in requirement_markers]
        # Also pick frequent distinctive tokens from standards
        distinctive = [w for w in list(std_keywords)[:400] if w not in tender_keywords]
        gap_samples = (marked + distinctive)[:12]
        if len(distinctive) > 80:
            findings.append(
                RiskFinding(
                    code="STD-ALIGN-001",
                    category="compliance",
                    severity=RiskSeverity.MEDIUM,
                    title={
                        LanguageCode.FA: "احتمال فاصله بین الزامات استاندارد و اسناد مناقصه",
                        LanguageCode.EN: "Likely gap between uploaded standards and tender documents",
                        LanguageCode.DE: "Wahrscheinliche Lücke zwischen Standards und Ausschreibungsunterlagen",
                        LanguageCode.FR: "Écart probable entre normes chargées et documents d'AO",
                    }[lang],
                    description={
                        LanguageCode.FA: "بخش قابل توجهی از واژگان استاندارد در اسناد مناقصه دیده نشد؛ نیاز به مرور تطبیقی دقیق‌تر است.",
                        LanguageCode.EN: "A large share of standard vocabulary is absent from tender text; detailed alignment review needed.",
                        LanguageCode.DE: "Ein großer Teil der Standardbegriffe fehlt in den Ausschreibungstexten; Detailabgleich nötig.",
                        LanguageCode.FR: "Une grande part du vocabulaire normatif est absente des documents d'AO; revue détaillée requise.",
                    }[lang],
                    recommendation={
                        LanguageCode.FA: "بندهای اجباری استانداردهای بارگذاری‌شده را به شرایط خصوصی و مشخصات فنی منتقل کنید.",
                        LanguageCode.EN: "Transfer mandatory clauses from uploaded standards into particular conditions and specs.",
                        LanguageCode.DE: "Verpflichtende Klauseln aus hochgeladenen Standards in besondere Bedingungen/Spezifikationen überführen.",
                        LanguageCode.FR: "Reprendre les clauses obligatoires des normes dans les conditions particulières et CCTP.",
                    }[lang],
                    financial_impact="medium",
                    schedule_impact="medium",
                    evidence=", ".join(gap_samples) if gap_samples else None,
                )
            )

    # Country profile note for non-Iran (still analyzable via uploaded standards)
    if country != CountryCode.IR and not by_cat[DocumentCategory.STANDARD]:
        findings.append(
            RiskFinding(
                code="COUNTRY-STD-001",
                category="compliance",
                severity=RiskSeverity.HIGH,
                title={
                    LanguageCode.FA: f"برای کشور {country.value} استاندارد محلی بارگذاری نشده",
                    LanguageCode.EN: f"No local standards uploaded for country {country.value}",
                    LanguageCode.DE: f"Keine lokalen Standards für Land {country.value} hochgeladen",
                    LanguageCode.FR: f"Aucune norme locale téléversée pour le pays {country.value}",
                }[lang],
                description={
                    LanguageCode.FA: "پروفایل این کشور به استانداردهای آپلودشده کاربر وابسته است.",
                    LanguageCode.EN: "This country profile depends on user-uploaded standards.",
                    LanguageCode.DE: "Dieses Länderprofil hängt von benutzerseitig hochgeladenen Standards ab.",
                    LanguageCode.FR: "Ce profil pays dépend des normes téléversées par l'utilisateur.",
                }[lang],
                recommendation={
                    LanguageCode.FA: "استانداردهای آلمان/کانادا/EU مورد استناد پروژه را بارگذاری کنید.",
                    LanguageCode.EN: "Upload the German/Canadian/EU standards referenced by the project.",
                    LanguageCode.DE: "Die für das Projekt maßgeblichen DE/CA/EU-Standards hochladen.",
                    LanguageCode.FR: "Téléverser les normes DE/CA/UE de référence du projet.",
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
                    LanguageCode.FA: "هیچ سندی برای تحلیل بارگذاری نشده",
                    LanguageCode.EN: "No documents uploaded for analysis",
                    LanguageCode.DE: "Keine Dokumente zur Analyse hochgeladen",
                    LanguageCode.FR: "Aucun document téléversé pour analyse",
                }[lang],
                description={
                    LanguageCode.FA: "برای تولید گزارش ریسک، حداقل اسناد مناقصه و استاندارد لازم است.",
                    LanguageCode.EN: "At least tender documents and standards are required to produce a risk report.",
                    LanguageCode.DE: "Mindestens Ausschreibungsunterlagen und Standards sind für den Risikobericht nötig.",
                    LanguageCode.FR: "Au minimum documents d'AO et normes sont requis pour le rapport de risques.",
                }[lang],
                recommendation={
                    LanguageCode.FA: "اسناد، نقشه‌ها، زمان‌بندی و استانداردها را بارگذاری کنید.",
                    LanguageCode.EN: "Upload tender docs, drawings, schedule, and standards.",
                    LanguageCode.DE: "Ausschreibung, Pläne, Terminplan und Standards hochladen.",
                    LanguageCode.FR: "Téléverser AO, plans, planning et normes.",
                }[lang],
                financial_impact="high",
                schedule_impact="high",
            )
        )

    high = sum(1 for f in findings if f.severity == RiskSeverity.HIGH)
    medium = sum(1 for f in findings if f.severity == RiskSeverity.MEDIUM)
    low = sum(1 for f in findings if f.severity == RiskSeverity.LOW)
    penalty = high * 12 + medium * 6 + low * 2
    score = max(0, min(100, 100 - penalty))

    summary = TRANSLATIONS["summary_template"][lang].format(
        score=score, high=high, medium=medium, low=low
    )

    return {
        "summary": summary,
        "readiness_score": score,
        "counts": {"high": high, "medium": medium, "low": low, "total": len(findings)},
        "findings": findings,
    }
