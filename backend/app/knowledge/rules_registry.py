"""Rule registry: global roots + country overrides (logic-as-data)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.models import CountryCode, DocumentCategory, LanguageCode, ProjectType, RiskSeverity


LangMap = dict[LanguageCode, str]


@dataclass
class RuleDef:
    code: str
    category: str
    severity: RiskSeverity
    title: LangMap
    description: LangMap
    recommendation: LangMap
    keywords_any: list[str] = field(default_factory=list)
    requires_category: DocumentCategory | None = None
    financial_impact: str | None = None
    schedule_impact: str | None = None
    # override metadata
    parent_code: str | None = None
    override_country: CountryCode | None = None
    inherit: bool = True
    logic_config: dict[str, Any] = field(default_factory=dict)
    applies_to: list[DocumentCategory] = field(default_factory=list)


def _L(fa: str, en: str, de: str, fr: str) -> LangMap:
    return {
        LanguageCode.FA: fa,
        LanguageCode.EN: en,
        LanguageCode.DE: de,
        LanguageCode.FR: fr,
    }


# ---------------------------------------------------------------------------
# Global baseline rules (roots)
# ---------------------------------------------------------------------------

GLOBAL_RULES: list[RuleDef] = [
    RuleDef(
        code="SCOPE-001",
        category="scope",
        severity=RiskSeverity.HIGH,
        keywords_any=["scope of work", "scope", "works comprise", "description of works"],
        title=_L(
            "شرح کار / محدوده کار مبهم یا ناقص",
            "Ambiguous or incomplete scope of work",
            "Unklarer oder unvollständiger Leistungsumfang",
            "Périmètre des travaux ambigu ou incomplet",
        ),
        description=_L(
            "بدون شرح کار شفاف، پیمانکار می‌تواند کارهای اضافی و ادعاهای مالی طرح کند.",
            "Without a clear scope, the contractor may claim extras and variations.",
            "Ohne klaren Leistungsumfang drohen Nachträge und Mehrkosten.",
            "Sans périmètre clair, l'entreprise peut réclamer des travaux supplémentaires.",
        ),
        recommendation=_L(
            "شرح کار تفصیلی و مرز مسئولیت‌ها را قبل از مناقصه تکمیل کنید.",
            "Complete a detailed scope and responsibility boundaries before tender.",
            "Detaillierten Leistungsumfang und Verantwortlichkeiten vor Ausschreibung ergänzen.",
            "Compléter le périmètre détaillé et les responsabilités avant l'AO.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        logic_config={"check": "keywords_missing"},
    ),
    RuleDef(
        code="BOQ-001",
        category="financial",
        severity=RiskSeverity.HIGH,
        keywords_any=["bill of quantities", "boq", "schedule of rates", "unit price", "quantities"],
        title=_L(
            "فهرست مقادیر / برآورد ناقص یا غایب",
            "Missing or incomplete bill of quantities / estimate",
            "Fehlendes oder unvollständiges Leistungsverzeichnis",
            "DPGF / métré manquant ou incomplet",
        ),
        description=_L(
            "نقص در مقادیر مبنای ادعاهای افزایش مبلغ و اختلاف پرداخت است.",
            "Quantity gaps commonly drive contract value claims and payment disputes.",
            "Mengenlücken führen häufig zu Nachträgen und Zahlungsstreitigkeiten.",
            "Les écarts de quantités génèrent souvent des réclamations financières.",
        ),
        recommendation=_L(
            "BoQ را با نقشه‌ها و مشخصات فنی هم‌راستا کنید.",
            "Cross-check BoQ against drawings and specifications.",
            "LV mit Plänen und Spezifikationen abgleichen.",
            "Recouper le métré avec plans et spécifications.",
        ),
        financial_impact="high",
        schedule_impact="low",
        logic_config={"check": "keywords_missing", "boq_formats": ["generic"]},
    ),
    RuleDef(
        code="TIME-001",
        category="schedule",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["schedule", "programme", "milestone", "completion date", "duration", "time for completion"],
        title=_L(
            "جزئیات برنامه زمان‌بندی بارگذاری‌شده ناکافی است",
            "Uploaded schedule lacks sufficient detail",
            "Hochgeladener Terminplan unzureichend detailliert",
            "Planning téléversé insuffisamment détaillé",
        ),
        description=_L(
            "فایل زمان‌بندی هست اما مایلستون/مسیر بحرانی به‌قدر کافی روشن نیست.",
            "A schedule file exists but milestones/critical path are unclear.",
            "Terminplan vorhanden, aber Meilensteine/kritischer Pfad unklar.",
            "Un planning existe mais jalons/chemin critique peu clairs.",
        ),
        recommendation=_L(
            "برنامه مبنا، مایلستون‌ها و قواعد تمدید مدت را صریح کنید.",
            "Define baseline schedule, milestones, and extension-of-time rules.",
            "Basisterminplan, Meilensteine und Bauzeitverlängerung klar festlegen.",
            "Définir planning de référence, jalons et règles de prolongation.",
        ),
        financial_impact="medium",
        schedule_impact="high",
        # Only assess schedule quality when a schedule file was uploaded.
        logic_config={"only_if_category": "schedule", "check": "keywords_missing"},
    ),
    RuleDef(
        code="SCHED-001",
        category="schedule",
        severity=RiskSeverity.MEDIUM,
        requires_category=DocumentCategory.SCHEDULE,
        title=_L(
            "برنامه زمان‌بندی بارگذاری نشده (اختیاری)",
            "Schedule not uploaded (optional)",
            "Kein Terminplan hochgeladen (optional)",
            "Planning non téléversé (optionnel)",
        ),
        description=_L(
            "نبود برنامه زمان‌بندی مانع تحلیل نیست؛ فقط ریسک تأخیر/تمدید کمتر پوشش داده می‌شود.",
            "Missing schedule does not block analysis; delay/EOT coverage is weaker.",
            "Fehlender Terminplan blockiert die Analyse nicht; Verzugsrisiko ist schwächer abgedeckt.",
            "L'absence de planning ne bloque pas l'analyse; couverture retard/EOT plus faible.",
        ),
        recommendation=_L(
            "در صورت وجود، برنامه مبنا را بعداً اضافه کنید؛ فعلاً می‌توانید تحلیل را ادامه دهید.",
            "Add a baseline schedule later if available; you can continue analysis now.",
            "Basisterminplan später nachreichen; Analyse jetzt fortsetzen.",
            "Ajouter un planning de référence plus tard; poursuivre l'analyse maintenant.",
        ),
        financial_impact="low",
        schedule_impact="medium",
    ),
    RuleDef(
        code="CLAIM-001",
        category="claims",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["variation", "change order", "claim", "compensation event", "instruction"],
        title=_L(
            "مکانیسم ادعا / کارهای اضافی تعریف نشده",
            "Claim / variation mechanism not defined",
            "Nachtrags-/Claim-Mechanismus nicht definiert",
            "Mécanisme de réclamation / avenant non défini",
        ),
        description=_L(
            "نبود فرآیند شفاف تغییر کار، بار مالی پیش‌بینی‌نشده برای کارفرما ایجاد می‌کند.",
            "Unclear variation process creates uncontrolled employer cost exposure.",
            "Unklarer Nachtragsprozess erzeugt unkontrollierte Auftraggeberkosten.",
            "Un processus d'avenant flou expose le maître d'ouvrage à des surcoûts.",
        ),
        recommendation=_L(
            "فرآیند ابلاغ، قیمت‌گذاری و سقف تغییرات را قید کنید.",
            "Specify notice, pricing, and caps for variations.",
            "Anzeige, Preisbildung und Obergrenzen für Nachträge regeln.",
            "Préciser notification, valorisation et plafonds des avenants.",
        ),
        financial_impact="high",
        schedule_impact="medium",
    ),
    RuleDef(
        code="PAY-001",
        category="financial",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["payment", "retention", "advance payment", "interim payment", "security", "bond"],
        title=_L(
            "شرایط پرداخت و ضمانت‌ها ناقص به نظر می‌رسد",
            "Payment and security terms appear incomplete",
            "Zahlungs- und Sicherheitsbedingungen wirken unvollständig",
            "Conditions de paiement et garanties semblent incomplètes",
        ),
        description=_L(
            "ابهام در پرداخت/ضمانت‌نامه جریان نقدی و اختلافات مالی می‌سازد.",
            "Ambiguity in payment/securities creates cash-flow and dispute risk.",
            "Unklare Zahlungen/Sicherheiten erzeugen Cashflow- und Streitrisiko.",
            "L'ambiguïté paiement/garanties crée un risque de trésorerie et de litige.",
        ),
        recommendation=_L(
            "پیش‌پرداخت، کسور، و مهلت رسیدگی پرداخت را شفاف کنید.",
            "Clarify advance payment, retention, and payment review periods.",
            "Abschlag, Sicherheitseinbehalt und Prüffristen klar regeln.",
            "Clarifier avance, retenue et délais de visa des situations.",
        ),
        financial_impact="high",
        schedule_impact="low",
    ),
    RuleDef(
        code="RESP-001",
        category="compliance",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["responsibility", "liable", "liability", "duty", "indemnity", "shall be responsible"],
        title=_L(
            "بندهای مسئولیت / تعهدات مبهم",
            "Unclear responsibility / liability clauses",
            "Unklare Verantwortungs-/Haftungsklauseln",
            "Clauses de responsabilité peu claires",
        ),
        description=_L(
            "ابهام در تخصیص مسئولیت، اختلاف و هزینه پنهان برای کارفرما می‌سازد.",
            "Ambiguous responsibility allocation creates dispute and hidden employer cost.",
            "Unklare Verantwortungszuweisung erzeugt Streit und versteckte Kosten.",
            "Une allocation floue des responsabilités crée litiges et coûts cachés.",
        ),
        recommendation=_L(
            "جدول مسئولیت‌ها و ارجاع به چارچوب حقوقی کشور را تکمیل کنید.",
            "Complete a responsibility matrix referencing the country legal framework.",
            "Verantwortungsmatrix mit Bezug zum nationalen Rechtsrahmen ergänzen.",
            "Compléter une matrice de responsabilités liée au cadre juridique local.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        logic_config={"prompt_code": "ANALYZE_RESPONSIBILITY_CLAUSES"},
    ),
    RuleDef(
        code="DRAW-001",
        category="technical",
        severity=RiskSeverity.HIGH,
        requires_category=DocumentCategory.DRAWING,
        title=_L(
            "نقشه‌های پروژه بارگذاری نشده",
            "Project drawings not uploaded",
            "Projektpläne nicht hochgeladen",
            "Plans du projet non téléversés",
        ),
        description=_L(
            "بدون نقشه، تعارض با متره و مشخصات دیر کشف می‌شود.",
            "Without drawings, conflicts with BoQ/specs are found late.",
            "Ohne Pläne werden Konflikte mit LV/Spezifikation spät erkannt.",
            "Sans plans, les conflits métré/specs apparaissent tard.",
        ),
        recommendation=_L(
            "بسته نقشه‌های مصوب را قبل از مناقصه بارگذاری کنید.",
            "Upload the approved drawing package before tender.",
            "Genehmigtes Plansatz vor Ausschreibung hochladen.",
            "Téléverser le jeu de plans approuvé avant l'AO.",
        ),
        financial_impact="high",
        schedule_impact="high",
    ),
    RuleDef(
        code="STD-001",
        category="compliance",
        severity=RiskSeverity.HIGH,
        requires_category=DocumentCategory.STANDARD,
        title=_L(
            "هیچ استاندارد مرجعی بارگذاری نشده",
            "No reference standards uploaded",
            "Keine Referenzstandards hochgeladen",
            "Aucune norme de référence téléversée",
        ),
        description=_L(
            "بدون استاندارد مبنا، انطباق منطقه‌ای ضعیف می‌شود.",
            "Without baseline standards, regional compliance weakens.",
            "Ohne Basisstandards ist die regionale Compliance schwach.",
            "Sans normes de référence, la conformité régionale s'affaiblit.",
        ),
        recommendation=_L(
            "استانداردهای اجباری کشور پروژه را بارگذاری کنید.",
            "Upload mandatory standards for the project country.",
            "Verpflichtende Landesstandards hochladen.",
            "Téléverser les normes obligatoires du pays du projet.",
        ),
        financial_impact="medium",
        schedule_impact="medium",
    ),
]


# ---------------------------------------------------------------------------
# Country overrides (parent_code + override_country) — merge keywords/logic
# ---------------------------------------------------------------------------

COUNTRY_OVERRIDES: list[RuleDef] = [
    # Iran
    RuleDef(
        code="SCOPE-001",
        parent_code="SCOPE-001",
        override_country=CountryCode.IR,
        category="scope",
        severity=RiskSeverity.HIGH,
        keywords_any=["شرح کار", "محدوده کار", "کارهای موضوع پیمان", "scope"],
        title=_L(
            "شرح کار / محدوده کار مبهم یا ناقص (ایران)",
            "Ambiguous scope of work (Iran profile)",
            "Unklarer Leistungsumfang (Iran)",
            "Périmètre ambigu (Iran)",
        ),
        description=_L(
            "در پروژه‌های ایران ابهام شرح کار معمولاً به دستورکار و ادعا منجر می‌شود.",
            "In Iranian tenders, scope gaps often drive site instructions and claims.",
            "In iranischen Ausschreibungen führen Leistungslücken oft zu Nachträgen.",
            "En Iran, les lacunes de périmètre génèrent souvent des avenants.",
        ),
        recommendation=_L(
            "شرح کار را با فهارس بها و شرایط خصوصی هم‌راستا کنید.",
            "Align scope with Fehrest Baha items and particular conditions.",
            "Leistungsumfang mit Fehrest-Baha und besonderen Bedingungen abstimmen.",
            "Aligner le périmètre avec Fehrest Baha et conditions particulières.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
        logic_config={"statutes": ["شرایط عمومی پیمان"], "boq_format": "fehrest_baha"},
    ),
    RuleDef(
        code="BOQ-001",
        parent_code="BOQ-001",
        override_country=CountryCode.IR,
        category="financial",
        severity=RiskSeverity.HIGH,
        keywords_any=["فهرست بها", "متره", "برآورد", "جدول مقادیر", "boq", "bill of quantities"],
        title=_L(
            "فهرست بها / مقادیر ناقص (ایران)",
            "Incomplete Fehrest Baha / quantities (Iran)",
            "Unvollständiges Fehrest Baha (Iran)",
            "Fehrest Baha incomplet (Iran)",
        ),
        description=_L(
            "نقص فهارس بها منبع اصلی اختلاف مالی در پروژه‌های ایران است.",
            "Fehrest Baha gaps are a primary Iranian cost-dispute driver.",
            "Lücken im Fehrest Baha sind ein Hauptkostentreiber in Iran.",
            "Les lacunes Fehrest Baha sont un risque financier majeur en Iran.",
        ),
        recommendation=_L(
            "ردیف‌های فهرست بها را با نقشه‌ها کنترل متقابل کنید.",
            "Cross-check Fehrest Baha line items against drawings.",
            "Fehrest-Baha-Positionen gegen Pläne prüfen.",
            "Contrôler les postes Fehrest Baha par rapport aux plans.",
        ),
        financial_impact="high",
        schedule_impact="low",
        inherit=True,
        logic_config={"boq_formats": ["fehrest_baha"], "statutes": ["فهرست بها"]},
    ),
    RuleDef(
        code="TIME-001",
        parent_code="TIME-001",
        override_country=CountryCode.IR,
        category="schedule",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["برنامه زمان", "مدت پیمان", "تأخیر", "زمان‌بندی", "schedule", "milestone"],
        title=_L(
            "جزئیات برنامه زمان‌بندی ناکافی است (ایران)",
            "Uploaded schedule lacks detail (Iran)",
            "Terminplan-Detail unzureichend (Iran)",
            "Détail du planning insuffisant (Iran)",
        ),
        description=_L(
            "فایل زمان‌بندی هست اما مدت/مایلستون برای تمدید و جریمه شفاف نیست.",
            "Schedule uploaded but duration/milestones for EOT/delay damages are unclear.",
            "Terminplan vorhanden, Laufzeit/Meilensteine für Verzug unklar.",
            "Planning présent mais durée/jalons pour EOT peu clairs.",
        ),
        recommendation=_L(
            "مدت پیمان، مایلستون پرداخت و شرایط تمدید را در شرایط خصوصی بنویسید.",
            "State contract duration, payment milestones, and EOT rules in particular conditions.",
            "Vertragslaufzeit, Zahlungsmeilensteine und Verlängerungsregeln festlegen.",
            "Fixer durée, jalons de paiement et règles de prolongation.",
        ),
        financial_impact="medium",
        schedule_impact="high",
        inherit=True,
        logic_config={"only_if_category": "schedule"},
    ),
    RuleDef(
        code="CLAIM-001",
        parent_code="CLAIM-001",
        override_country=CountryCode.IR,
        category="claims",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["ادعا", "تغییر مقادیر", "دستور کار", "کارهای اضافی", "claim", "variation"],
        title=_L(
            "مکانیسم ادعا/دستورکار تعریف نشده (ایران)",
            "Claim / site-instruction mechanism missing (Iran)",
            "Claim-/Anweisungsmechanismus fehlt (Iran)",
            "Mécanisme claim/ordre de service manquant (Iran)",
        ),
        description=_L(
            "نبود فرآیند دستورکار و ادعا بار مالی کارفرما را بالا می‌برد.",
            "Missing instruction/claim process increases employer cost exposure.",
            "Fehlender Anweisungs-/Claim-Prozess erhöht Auftraggeberkosten.",
            "L'absence de processus d'ordre/claim augmente le risque coût.",
        ),
        recommendation=_L(
            "فرآیند ابلاغ دستورکار، قیمت‌گذاری و سقف تغییرات را قید کنید.",
            "Define instruction notice, pricing, and variation caps.",
            "Anordnung, Preisbildung und Nachtragsobergrenzen regeln.",
            "Définir notification, valorisation et plafonds d'avenants.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
    ),
    RuleDef(
        code="PAY-001",
        parent_code="PAY-001",
        override_country=CountryCode.IR,
        category="financial",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["پرداخت", "صورت وضعیت", "پیش پرداخت", "ضمانت", "وجه الضمان", "payment", "retention"],
        title=_L(
            "شرایط پرداخت/ضمانت ناقص (ایران)",
            "Incomplete payment/security terms (Iran)",
            "Unvollständige Zahlungs-/Sicherheitsbedingungen (Iran)",
            "Paiement/garanties incomplets (Iran)",
        ),
        description=_L(
            "ابهام صورت‌وضعیت و ضمانت‌نامه اختلاف رایج کارفرما-پیمانکار است.",
            "Ambiguous interim payment and bonds are a common Iranian dispute source.",
            "Unklare Abschläge/Bürgschaften sind ein häufiger Streitpunkt.",
            "Paiements intermédiaires et garanties ambigus sont fréquents.",
        ),
        recommendation=_L(
            "نسبت پیش‌پرداخت، کسور وجه الضمان و مهلت رسیدگی را شفاف کنید.",
            "Clarify advance %, retention, and interim payment review periods.",
            "Abschlag, Einbehalt und Prüffristen klarstellen.",
            "Clarifier avance, retenue et délais de visa.",
        ),
        financial_impact="high",
        schedule_impact="low",
        inherit=True,
        logic_config={"terms": ["تعدیل", "صورت وضعیت"]},
    ),
    RuleDef(
        code="RESP-001",
        parent_code="RESP-001",
        override_country=CountryCode.IR,
        category="compliance",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["مسئولیت", "تعهدات", "مسئول", "ضمانت اجرا", "responsibility", "liable"],
        title=_L(
            "بندهای مسئولیت مبهم (ایران)",
            "Unclear responsibility clauses (Iran)",
            "Unklare Verantwortlichkeiten (Iran)",
            "Responsabilités peu claires (Iran)",
        ),
        description=_L(
            "بدون ارجاع شفاف به شرایط عمومی/خصوصی، تخصیص ریسک ضعیف است.",
            "Without clear General/Particular Conditions linkage, risk allocation is weak.",
            "Ohne klare Bezugnahme auf allgemeine/besondere Bedingungen ist die Risikoallokation schwach.",
            "Sans lien clair aux conditions générales/particulières, l'allocation des risques est faible.",
        ),
        recommendation=_L(
            "جدول مسئولیت را به شرایط عمومی پیمان و کدهای ملی پیوند دهید.",
            "Link the responsibility matrix to GCC and national codes.",
            "Verantwortungsmatrix an GCC und nationale Codes koppeln.",
            "Lier la matrice de responsabilités aux CCG et codes nationaux.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
        logic_config={
            "prompt_code": "ANALYZE_RESPONSIBILITY_CLAUSES",
            "statutes": ["شرایط عمومی پیمان", "شرایط خصوصی"],
        },
    ),
    # Germany
    RuleDef(
        code="SCOPE-001",
        parent_code="SCOPE-001",
        override_country=CountryCode.DE,
        category="scope",
        severity=RiskSeverity.HIGH,
        keywords_any=["Leistungsbeschreibung", "Leistungsumfang", "Baubeschreibung", "scope of work", "scope"],
        title=_L(
            "Leistungsumfang unklar (Deutschland)",
            "Unclear scope / Leistungsbeschreibung (Germany)",
            "Unklare Leistungsbeschreibung (Deutschland)",
            "Descriptif des prestations flou (Allemagne)",
        ),
        description=_L(
            "در آلمان ابهام Leistungsbeschreibung معمولاً به Nachtrag منجر می‌شود.",
            "In Germany, unclear Leistungsbeschreibung commonly drives Nachträge.",
            "Unklare Leistungsbeschreibung führt häufig zu Nachträgen.",
            "Un descriptif flou génère souvent des avenants (Nachtrag).",
        ),
        recommendation=_L(
            "Leistungsbeschreibung را با VOB/B و LV هم‌راستا کنید.",
            "Align Leistungsbeschreibung with VOB/B and the LV (GAEB).",
            "Leistungsbeschreibung mit VOB/B und LV (GAEB) abstimmen.",
            "Aligner le descriptif avec VOB/B et le LV (GAEB).",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
        logic_config={"statutes": ["VOB/B", "BGB"], "boq_format": "gaeb"},
    ),
    RuleDef(
        code="BOQ-001",
        parent_code="BOQ-001",
        override_country=CountryCode.DE,
        category="financial",
        severity=RiskSeverity.HIGH,
        keywords_any=["Leistungsverzeichnis", "LV", "GAEB", "Position", "Mengen", "bill of quantities"],
        title=_L(
            "Leistungsverzeichnis / GAEB ناقص (آلمان)",
            "Incomplete LV / GAEB quantities (Germany)",
            "Unvollständiges LV/GAEB (Deutschland)",
            "LV/GAEB incomplet (Allemagne)",
        ),
        description=_L(
            "نقص LV/GAEB منبع اصلی Nachtrag و اختلاف مقدار است.",
            "LV/GAEB gaps are a primary driver of quantity claims in DE.",
            "Lücken im LV/GAEB sind ein Haupttreiber für Mengennachträge.",
            "Les lacunes LV/GAEB génèrent des réclamations de quantités.",
        ),
        recommendation=_L(
            "Positionهای GAEB را با نقشه و Leistungsbeschreibung کنترل کنید.",
            "Cross-check GAEB positions against drawings and specs.",
            "GAEB-Positionen gegen Pläne und Leistungsbeschreibung prüfen.",
            "Contrôler les postes GAEB par rapport aux plans et specs.",
        ),
        financial_impact="high",
        schedule_impact="low",
        inherit=True,
        logic_config={"boq_formats": ["gaeb"], "statutes": ["VOB/C", "GAEB"]},
    ),
    RuleDef(
        code="CLAIM-001",
        parent_code="CLAIM-001",
        override_country=CountryCode.DE,
        category="claims",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["Nachtrag", "Nachtragsmanagement", "Anordnung", "Mehrvergütung", "variation", "claim"],
        title=_L(
            "Nachtragsmechanismus unklar (Deutschland)",
            "Unclear Nachtrag / variation mechanism (Germany)",
            "Unklarer Nachtragsmechanismus (Deutschland)",
            "Mécanisme Nachtrag flou (Allemagne)",
        ),
        description=_L(
            "بدون فرآیند شفاف Nachtrag، هزینه کارفرما کنترل‌ناپذیر می‌شود.",
            "Without a clear Nachtrag process, employer cost becomes uncontrolled.",
            "Ohne klares Nachtragsverfahren werden Kosten unkontrollierbar.",
            "Sans processus Nachtrag clair, les coûts deviennent incontrôlables.",
        ),
        recommendation=_L(
            "Anzeige، Fristen و Preisbildung برای Nachtrag را در قرارداد بنویسید.",
            "Define notice, deadlines, and pricing for Nachträge in the contract.",
            "Anzeige, Fristen und Preisbildung für Nachträge vertraglich regeln.",
            "Définir notification, délais et valorisation des Nachträge.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
        logic_config={"statutes": ["VOB/B", "BGB"]},
    ),
    RuleDef(
        code="RESP-001",
        parent_code="RESP-001",
        override_country=CountryCode.DE,
        category="compliance",
        severity=RiskSeverity.MEDIUM,
        keywords_any=[
            "Gewährleistung",
            "Haftung",
            "Verkehrssicherung",
            "Verantwortung",
            "liability",
            "responsibility",
        ],
        title=_L(
            "Haftung/Gewährleistung unklar (Deutschland)",
            "Unclear liability / Gewährleistung (Germany)",
            "Unklare Haftung/Gewährleistung (Deutschland)",
            "Responsabilité/garantie floue (Allemagne)",
        ),
        description=_L(
            "ابهام Haftung و Gewährleistung تحت BGB/VOB ریسک کارفرما را بالا می‌برد.",
            "Ambiguous Haftung/Gewährleistung under BGB/VOB raises employer risk.",
            "Unklare Haftung/Gewährleistung nach BGB/VOB erhöht Auftraggeberrisiko.",
            "Une Haftung/Gewährleistung floue augmente le risque maître d'ouvrage.",
        ),
        recommendation=_L(
            "بندهای Haftung را با ارجاع صریح به VOB/B و BGB تکمیل کنید.",
            "Clarify liability clauses with explicit VOB/B and BGB references.",
            "Haftungsklauseln mit klarem VOB/B- und BGB-Bezug schärfen.",
            "Clarifier les clauses avec références explicites VOB/B et BGB.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
        logic_config={
            "prompt_code": "ANALYZE_RESPONSIBILITY_CLAUSES",
            "statutes": ["BGB", "VOB/B"],
            "terms": ["Gewährleistung", "Verkehrssicherung"],
        },
    ),
    RuleDef(
        code="PAY-001",
        parent_code="PAY-001",
        override_country=CountryCode.DE,
        category="financial",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["Abschlag", "Sicherheitseinbehalt", "Bürgschaft", "Zahlung", "payment", "retention"],
        title=_L(
            "Zahlungs-/Sicherheitsbedingungen lückenhaft (DE)",
            "Incomplete payment/security terms (Germany)",
            "Lückenhafte Zahlungs-/Sicherheitsbedingungen (DE)",
            "Paiement/sûretés incomplets (Allemagne)",
        ),
        description=_L(
            "ابهام Abschlag و Bürgschaft اختلاف نقدینگی می‌سازد.",
            "Ambiguous Abschlag and bonds create cash-flow disputes.",
            "Unklare Abschläge/Bürgschaften erzeugen Liquiditätsstreit.",
            "Abschlag et cautions ambigus créent des litiges de trésorerie.",
        ),
        recommendation=_L(
            "Abschlagszahlungen، Einbehalt و Sicherheiten را شفاف کنید.",
            "Clarify interim payments, retention, and securities.",
            "Abschläge, Einbehalt und Sicherheiten klar regeln.",
            "Clarifier acomptes, retenue et sûretés.",
        ),
        financial_impact="high",
        schedule_impact="low",
        inherit=True,
    ),
    # Canada
    RuleDef(
        code="SCOPE-001",
        parent_code="SCOPE-001",
        override_country=CountryCode.CA,
        category="scope",
        severity=RiskSeverity.HIGH,
        keywords_any=["scope of work", "work included", "work excluded", "division 01", "scope"],
        title=_L(
            "Scope of work unclear (Canada)",
            "Unclear scope of work (Canada)",
            "Unklarer Leistungsumfang (Kanada)",
            "Périmètre peu clair (Canada)",
        ),
        description=_L(
            "در کانادا ابهام scope معمولاً به change order منجر می‌شود.",
            "In Canada, scope gaps commonly drive change orders.",
            "In Kanada führen Scope-Lücken häufig zu Change Orders.",
            "Au Canada, les lacunes de scope génèrent des change orders.",
        ),
        recommendation=_L(
            "Scope را با CCDC supplementary conditions هم‌راستا کنید.",
            "Align scope with CCDC supplementary conditions.",
            "Scope mit CCDC Supplementary Conditions abstimmen.",
            "Aligner le scope avec les conditions supplémentaires CCDC.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
        logic_config={"statutes": ["CCDC"], "boq_format": "trade_boq"},
    ),
    RuleDef(
        code="BOQ-001",
        parent_code="BOQ-001",
        override_country=CountryCode.CA,
        category="financial",
        severity=RiskSeverity.HIGH,
        keywords_any=["unit price", "schedule of prices", "quantity", "trade breakdown", "boq", "bill of quantities"],
        title=_L(
            "Quantities / unit prices incomplete (Canada)",
            "Incomplete quantities / unit prices (Canada)",
            "Unvollständige Mengen/Einheitspreise (Kanada)",
            "Quantités / prix unitaires incomplets (Canada)",
        ),
        description=_L(
            "نقص schedule of prices اختلاف پرداخت و change را بالا می‌برد.",
            "Gaps in the schedule of prices drive payment and change disputes.",
            "Lücken im Preisverzeichnis treiben Zahlungs- und Change-Streit.",
            "Les lacunes du bordereau de prix génèrent litiges de paiement.",
        ),
        recommendation=_L(
            "Trade breakdown را با نقشه و spec کنترل کنید.",
            "Cross-check trade breakdown against drawings and specs.",
            "Trade-Breakdown gegen Pläne und Specs prüfen.",
            "Contrôler la ventilation des lots par rapport aux plans/specs.",
        ),
        financial_impact="high",
        schedule_impact="low",
        inherit=True,
        logic_config={"boq_formats": ["trade_boq"]},
    ),
    RuleDef(
        code="PAY-001",
        parent_code="PAY-001",
        override_country=CountryCode.CA,
        category="financial",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["holdback", "progress payment", "statutory declaration", "payment", "retention", "bond"],
        title=_L(
            "Holdback / payment terms incomplete (Canada)",
            "Incomplete holdback / payment terms (Canada)",
            "Unvollständige Holdback-/Zahlungsbedingungen (Kanada)",
            "Holdback / paiement incomplets (Canada)",
        ),
        description=_L(
            "ابهام holdback و progress payment اختلاف نقدی رایج است.",
            "Ambiguous holdback and progress payments are a common cash dispute.",
            "Unklarer Holdback und Abschlagszahlungen sind streitanfällig.",
            "Holdback et acomptes ambigus sont sources de litiges.",
        ),
        recommendation=_L(
            "Holdback٪، دوره پرداخت و مدارک progressive را صریح کنید.",
            "State holdback %, payment cycle, and progress documentation.",
            "Holdback-%, Zahlungszyklus und Nachweise klar festlegen.",
            "Fixer % holdback, cycle de paiement et pièces justificatives.",
        ),
        financial_impact="high",
        schedule_impact="low",
        inherit=True,
        logic_config={"terms": ["holdback", "CCDC"]},
    ),
    RuleDef(
        code="RESP-001",
        parent_code="RESP-001",
        override_country=CountryCode.CA,
        category="compliance",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["GC ", "supplementary conditions", "indemnify", "liable", "responsibility", "insurance"],
        title=_L(
            "Responsibility under CCDC unclear (Canada)",
            "Unclear CCDC responsibility allocation (Canada)",
            "Unklare CCDC-Verantwortlichkeiten (Kanada)",
            "Responsabilités CCDC peu claires (Canada)",
        ),
        description=_L(
            "بدون شفافیت GC/supplementary conditions تخصیص ریسک ضعیف است.",
            "Without clear GC/supplementary conditions, risk allocation is weak.",
            "Ohne klare GC/Supplementary Conditions ist die Risikoallokation schwach.",
            "Sans GC/conditions supplémentaires claires, l'allocation des risques est faible.",
        ),
        recommendation=_L(
            "مسئولیت‌ها را با ارجاع به فرم CCDC و بیمه تکمیل کنید.",
            "Clarify responsibilities with CCDC form and insurance references.",
            "Verantwortlichkeiten mit CCDC-Formular und Versicherungen klären.",
            "Clarifier les responsabilités via formulaire CCDC et assurances.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
        logic_config={
            "prompt_code": "ANALYZE_RESPONSIBILITY_CLAUSES",
            "statutes": ["CCDC", "NBC", "CSA"],
        },
    ),
    RuleDef(
        code="CLAIM-001",
        parent_code="CLAIM-001",
        override_country=CountryCode.CA,
        category="claims",
        severity=RiskSeverity.MEDIUM,
        keywords_any=["change order", "change directive", "claim", "notice", "GC"],
        title=_L(
            "Change order mechanism unclear (Canada)",
            "Unclear change order mechanism (Canada)",
            "Unklarer Change-Order-Mechanismus (Kanada)",
            "Mécanisme de change order flou (Canada)",
        ),
        description=_L(
            "نبود فرآیند change order/directive هزینه را کنترل‌ناپذیر می‌کند.",
            "Missing change order/directive process makes cost uncontrolled.",
            "Fehlendes Change-Order-Verfahren macht Kosten unkontrollierbar.",
            "Sans processus de change order, les coûts deviennent incontrôlables.",
        ),
        recommendation=_L(
            "Notice periods و pricing برای change را مطابق CCDC بنویسید.",
            "Define notice periods and pricing for changes per CCDC practice.",
            "Anzeigefristen und Preisbildung für Changes nach CCDC regeln.",
            "Définir délais de notification et valorisation selon CCDC.",
        ),
        financial_impact="high",
        schedule_impact="medium",
        inherit=True,
    ),
]


RULESETS: dict[str, list[str]] = {
    "GLOBAL_BASE": [r.code for r in GLOBAL_RULES],
    "IR_CORE_V1": [r.code for r in GLOBAL_RULES],
    "DE_CORE_V1": [r.code for r in GLOBAL_RULES],
    "CA_CORE_V1": [r.code for r in GLOBAL_RULES],
    "EU_CORE_V1": [r.code for r in GLOBAL_RULES],
}


def _index_globals() -> dict[str, RuleDef]:
    return {r.code: r for r in GLOBAL_RULES}


def _merge_rule(base: RuleDef, override: RuleDef) -> RuleDef:
    if not override.inherit:
        return deepcopy(override)
    merged = deepcopy(base)
    merged.title = override.title or base.title
    merged.description = override.description or base.description
    merged.recommendation = override.recommendation or base.recommendation
    merged.severity = override.severity or base.severity
    merged.category = override.category or base.category
    merged.financial_impact = override.financial_impact or base.financial_impact
    merged.schedule_impact = override.schedule_impact or base.schedule_impact
    merged.requires_category = override.requires_category or base.requires_category
    # keyword union
    kw = list(dict.fromkeys([*(base.keywords_any or []), *(override.keywords_any or [])]))
    merged.keywords_any = kw
    cfg = deepcopy(base.logic_config or {})
    cfg.update(override.logic_config or {})
    merged.logic_config = cfg
    merged.parent_code = base.code
    merged.override_country = override.override_country
    merged.inherit = True
    merged.code = base.code  # stable family code
    return merged


def resolve_rules_for_project(
    *,
    country: CountryCode,
    project_type: ProjectType | None = None,
    ruleset_code: str | None = None,
) -> list[RuleDef]:
    """Pick global root, then apply best country override (data-driven)."""
    _ = project_type  # reserved for type-specific members later
    globals_ = _index_globals()
    overrides = [o for o in COUNTRY_OVERRIDES if o.override_country == country]

    profile_ruleset = ruleset_code
    if not profile_ruleset:
        from app.knowledge.country_profiles import get_country_profile

        profile_ruleset = get_country_profile(country).default_ruleset_code

    member_codes = RULESETS.get(profile_ruleset) or RULESETS["GLOBAL_BASE"]
    resolved: list[RuleDef] = []
    for code in member_codes:
        base = globals_.get(code)
        if not base:
            continue
        country_over = next((o for o in overrides if (o.parent_code or o.code) == code), None)
        resolved.append(_merge_rule(base, country_over) if country_over else deepcopy(base))
    return resolved
