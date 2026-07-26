"""Platform standards catalog + applicability (Country × ProjectType).

Catalog lives in code for MVP; ProjectStandard rows store per-project selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import CountryCode, ProjectType


@dataclass(frozen=True)
class StandardApplicability:
    country: CountryCode
    # None = all project types for that country
    project_types: frozenset[str] | None = None
    level: str = "recommended_default"  # mandatory_default | recommended_default | optional


@dataclass
class StandardDef:
    code: str
    standard_class: str  # technical | contractual | hybrid
    title_fa: str
    title_en: str
    title_de: str
    publisher: str
    country_home: CountryCode | None
    check_keywords: list[str] = field(default_factory=list)
    applicability: list[StandardApplicability] = field(default_factory=list)

    def title_for(self, lang: str) -> str:
        if lang == "fa":
            return self.title_fa
        if lang == "de":
            return self.title_de
        return self.title_en


_BUILDING = frozenset(
    {
        ProjectType.RESIDENTIAL.value,
        ProjectType.OFFICE.value,
        ProjectType.COMMERCIAL.value,
        ProjectType.MIXED_USE.value,
        ProjectType.HOSPITAL.value,
        ProjectType.EDUCATIONAL.value,
        ProjectType.HOSPITALITY.value,
        ProjectType.RETAIL.value,
        ProjectType.CULTURAL.value,
        ProjectType.SPORTS.value,
        ProjectType.DATA_CENTER.value,
        ProjectType.LABORATORY.value,
        ProjectType.WAREHOUSE.value,
        ProjectType.INDUSTRIAL.value,
        ProjectType.RENOVATION_FITOUT.value,
    }
)

_CIVIL = frozenset(
    {
        ProjectType.INFRASTRUCTURE.value,
        ProjectType.ROAD_HIGHWAY.value,
        ProjectType.BRIDGE.value,
        ProjectType.TUNNEL.value,
        ProjectType.RAILWAY.value,
        ProjectType.AIRPORT.value,
        ProjectType.PORT_MARINE.value,
        ProjectType.DAM_WATER.value,
        ProjectType.WATER_WASTEWATER.value,
        ProjectType.POWER_ENERGY.value,
        ProjectType.OIL_GAS.value,
        ProjectType.TELECOM.value,
        ProjectType.LANDSCAPE_URBAN.value,
    }
)


STANDARDS_CATALOG: list[StandardDef] = [
    # ---- Iran ----
    StandardDef(
        code="IR_GENERAL_CONDITIONS",
        standard_class="contractual",
        title_fa="شرایط عمومی پیمان",
        title_en="Iran General Conditions of Contract",
        title_de="Allgemeine Vertragsbedingungen (Iran)",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["شرایط عمومی", "پیمان", "کارفرما", "پیمانکار"],
        applicability=[
            StandardApplicability(CountryCode.IR, None, "mandatory_default"),
        ],
    ),
    StandardDef(
        code="IR_NBR",
        standard_class="technical",
        title_fa="مقررات ملی ساختمان (مباحث)",
        title_en="Iran National Building Regulations",
        title_de="Nationale Bauvorschriften Iran",
        publisher="Ministry of Roads & Urban Development",
        country_home=CountryCode.IR,
        check_keywords=["مبحث", "مقررات ملی", "ساختمان"],
        applicability=[
            StandardApplicability(CountryCode.IR, _BUILDING, "mandatory_default"),
            StandardApplicability(CountryCode.IR, _CIVIL, "recommended_default"),
        ],
    ),
    # Fehrest Baha family — multiple discipline lists (all selectable)
    StandardDef(
        code="IR_FEHREST_ABNIEH",
        standard_class="technical",
        title_fa="فهرست بهای ابنیه",
        title_en="Fehrest Baha — Building works",
        title_de="Fehrest Baha — Hochbau",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "ابنیه", "متره", "برآورد"],
        applicability=[
            StandardApplicability(CountryCode.IR, _BUILDING, "mandatory_default"),
            StandardApplicability(CountryCode.IR, _CIVIL, "recommended_default"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_TAASISAT_BARGH",
        standard_class="technical",
        title_fa="فهرست بهای تأسیسات برقی",
        title_en="Fehrest Baha — Electrical installations",
        title_de="Fehrest Baha — Elektro",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "تأسیسات برقی", "برق"],
        applicability=[
            StandardApplicability(CountryCode.IR, _BUILDING, "mandatory_default"),
            StandardApplicability(CountryCode.IR, _CIVIL, "recommended_default"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_TAASISAT_MECHANIC",
        standard_class="technical",
        title_fa="فهرست بهای تأسیسات مکانیکی",
        title_en="Fehrest Baha — Mechanical installations",
        title_de="Fehrest Baha — TGA / Mechanik",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "تأسیسات مکانیکی", "مکانیک"],
        applicability=[
            StandardApplicability(CountryCode.IR, _BUILDING, "mandatory_default"),
            StandardApplicability(CountryCode.IR, _CIVIL, "recommended_default"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_RAH",
        standard_class="technical",
        title_fa="فهرست بهای راه و باند و فرودگاه",
        title_en="Fehrest Baha — Road / runway / airport",
        title_de="Fehrest Baha — Straße / Flugplatz",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "راه", "باند", "فرودگاه"],
        applicability=[
            StandardApplicability(
                CountryCode.IR,
                frozenset(
                    {
                        ProjectType.INFRASTRUCTURE.value,
                        ProjectType.ROAD_HIGHWAY.value,
                        ProjectType.AIRPORT.value,
                        ProjectType.BRIDGE.value,
                        ProjectType.TUNNEL.value,
                    }
                ),
                "mandatory_default",
            ),
            StandardApplicability(CountryCode.IR, _BUILDING, "optional"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_RAHAN",
        standard_class="technical",
        title_fa="فهرست بهای راهداری و نگهداری",
        title_en="Fehrest Baha — Road maintenance",
        title_de="Fehrest Baha — Straßenunterhalt",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "راهداری", "نگهداری"],
        applicability=[
            StandardApplicability(
                CountryCode.IR,
                frozenset({ProjectType.ROAD_HIGHWAY.value, ProjectType.INFRASTRUCTURE.value}),
                "recommended_default",
            ),
            StandardApplicability(CountryCode.IR, None, "optional"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_AB",
        standard_class="technical",
        title_fa="فهرست بهای آب و شبکه آبیاری و زهکشی",
        title_en="Fehrest Baha — Water / irrigation / drainage",
        title_de="Fehrest Baha — Wasser / Bewässerung",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "آبیاری", "زهکشی", "آب"],
        applicability=[
            StandardApplicability(
                CountryCode.IR,
                frozenset(
                    {
                        ProjectType.WATER_WASTEWATER.value,
                        ProjectType.DAM_WATER.value,
                        ProjectType.INFRASTRUCTURE.value,
                    }
                ),
                "mandatory_default",
            ),
            StandardApplicability(CountryCode.IR, _BUILDING, "optional"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_FAZELAB",
        standard_class="technical",
        title_fa="فهرست بهای شبکه جمع‌آوری و انتقال فاضلاب",
        title_en="Fehrest Baha — Sewer / wastewater networks",
        title_de="Fehrest Baha — Abwasser",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "فاضلاب"],
        applicability=[
            StandardApplicability(
                CountryCode.IR,
                frozenset({ProjectType.WATER_WASTEWATER.value, ProjectType.INFRASTRUCTURE.value}),
                "recommended_default",
            ),
            StandardApplicability(CountryCode.IR, _BUILDING, "optional"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_MANABE_NATURAL",
        standard_class="technical",
        title_fa="فهرست بهای مرمت و نگهداری ابنیه و تأسیسات / منابع طبیعی (در صورت کاربرد)",
        title_en="Fehrest Baha — Related specialty lists (as applicable)",
        title_de="Fehrest Baha — Speziallisten",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "مرمت", "نگهداری"],
        applicability=[
            StandardApplicability(CountryCode.IR, None, "optional"),
        ],
    ),
    StandardDef(
        code="IR_FEHREST_BAHA",
        standard_class="technical",
        title_fa="فهرست بها (عمومی / مرجع سال پایه)",
        title_en="Fehrest Baha — General / base-year reference",
        title_de="Fehrest Baha — Allgemein",
        publisher="Plan & Budget Organization",
        country_home=CountryCode.IR,
        check_keywords=["فهرست بها", "متره", "برآورد", "ضریب"],
        applicability=[
            StandardApplicability(CountryCode.IR, None, "recommended_default"),
        ],
    ),
    StandardDef(
        code="IR_HSE",
        standard_class="hybrid",
        title_fa="الزامات ایمنی و بهداشت کارگاه",
        title_en="Iran site HSE requirements",
        title_de="Arbeitsschutz / HSE (Iran)",
        publisher="Various / Labour",
        country_home=CountryCode.IR,
        check_keywords=["ایمنی", "HSE", "بهداشت"],
        applicability=[
            StandardApplicability(CountryCode.IR, None, "recommended_default"),
        ],
    ),
    StandardDef(
        code="IR_ELECTRICAL",
        standard_class="technical",
        title_fa="مبحث ۱۳ / تأسیسات برقی",
        title_en="Iran electrical installations (Topic 13)",
        title_de="Elektroinstallationen Iran",
        publisher="National Building Regulations",
        country_home=CountryCode.IR,
        check_keywords=["برق", "الکتریکال", "مبحث ۱۳"],
        applicability=[
            StandardApplicability(CountryCode.IR, _BUILDING, "recommended_default"),
            StandardApplicability(CountryCode.IR, _CIVIL, "optional"),
        ],
    ),
    StandardDef(
        code="IR_FIRE",
        standard_class="technical",
        title_fa="مبحث ۳ / حفاظت در برابر حریق",
        title_en="Iran fire protection (Topic 3)",
        title_de="Brandschutz Iran",
        publisher="National Building Regulations",
        country_home=CountryCode.IR,
        check_keywords=["حریق", "آتش‌نشانی", "مبحث ۳"],
        applicability=[
            StandardApplicability(CountryCode.IR, _BUILDING, "recommended_default"),
        ],
    ),
    # ---- Germany ----
    StandardDef(
        code="DE_VOB_B",
        standard_class="contractual",
        title_fa="VOB/B — شرایط پیمان ساختمانی آلمان",
        title_en="VOB/B — German construction contract conditions",
        title_de="VOB/B — Allgemeine Vertragsbedingungen für Bauleistungen",
        publisher="DVA / DIN",
        country_home=CountryCode.DE,
        check_keywords=["VOB", "VOB/B", "Vergabe", "Nachtrag"],
        applicability=[
            StandardApplicability(CountryCode.DE, None, "mandatory_default"),
        ],
    ),
    StandardDef(
        code="DE_DIN_1045",
        standard_class="technical",
        title_fa="DIN 1045 — بتن و سازه‌های بتنی",
        title_en="DIN 1045 — Concrete structures",
        title_de="DIN 1045 — Tragwerke aus Beton",
        publisher="DIN",
        country_home=CountryCode.DE,
        check_keywords=["DIN 1045", "Betondeckung", "Expositionsklasse", "concrete cover"],
        applicability=[
            StandardApplicability(CountryCode.DE, _BUILDING, "mandatory_default"),
            StandardApplicability(CountryCode.DE, _CIVIL, "recommended_default"),
        ],
    ),
    StandardDef(
        code="DE_DIN_18202",
        standard_class="technical",
        title_fa="DIN 18202 — رواداری‌های ابعادی در ساختمان",
        title_en="DIN 18202 — Dimensional tolerances",
        title_de="DIN 18202 — Toleranzen im Hochbau",
        publisher="DIN",
        country_home=CountryCode.DE,
        check_keywords=["DIN 18202", "Toleranz"],
        applicability=[
            StandardApplicability(CountryCode.DE, _BUILDING, "recommended_default"),
        ],
    ),
    StandardDef(
        code="DE_HOAI",
        standard_class="contractual",
        title_fa="HOAI — تعرفه خدمات مهندسی",
        title_en="HOAI — Fee structure for architects/engineers",
        title_de="HOAI — Honorarordnung",
        publisher="BMWSB",
        country_home=CountryCode.DE,
        check_keywords=["HOAI", "Leistungsphase"],
        applicability=[
            StandardApplicability(CountryCode.DE, None, "optional"),
        ],
    ),
    StandardDef(
        code="DE_DIN_EN_1990",
        standard_class="technical",
        title_fa="Eurocode / DIN EN 1990 — مبانی طراحی سازه",
        title_en="Eurocode basis (DIN EN 1990)",
        title_de="DIN EN 1990 — Eurocode Grundlagen",
        publisher="DIN / CEN",
        country_home=CountryCode.DE,
        check_keywords=["Eurocode", "EN 1990", "DIN EN"],
        applicability=[
            StandardApplicability(CountryCode.DE, _BUILDING | _CIVIL, "recommended_default"),
        ],
    ),
    # ---- Canada ----
    StandardDef(
        code="CA_CCDC_2",
        standard_class="contractual",
        title_fa="CCDC 2 — پیمان ساخت کانادا",
        title_en="CCDC 2 — Stipulated Price Contract",
        title_de="CCDC 2 — Kanadischer Bauvertrag",
        publisher="CCDC",
        country_home=CountryCode.CA,
        check_keywords=["CCDC", "GC ", "holdback", "change order"],
        applicability=[
            StandardApplicability(CountryCode.CA, None, "mandatory_default"),
        ],
    ),
    StandardDef(
        code="CA_NBC",
        standard_class="technical",
        title_fa="NBC — مقررات ملی ساختمان کانادا",
        title_en="National Building Code of Canada",
        title_de="National Building Code of Canada",
        publisher="NRC",
        country_home=CountryCode.CA,
        check_keywords=["NBC", "National Building Code", "Division B"],
        applicability=[
            StandardApplicability(CountryCode.CA, _BUILDING, "mandatory_default"),
            StandardApplicability(CountryCode.CA, _CIVIL, "recommended_default"),
        ],
    ),
    StandardDef(
        code="CA_CSA_A23",
        standard_class="technical",
        title_fa="CSA A23 — بتن",
        title_en="CSA A23 — Concrete materials and methods",
        title_de="CSA A23 — Beton",
        publisher="CSA",
        country_home=CountryCode.CA,
        check_keywords=["CSA A23", "concrete", "cover"],
        applicability=[
            StandardApplicability(CountryCode.CA, _BUILDING | {ProjectType.BRIDGE.value}, "recommended_default"),
        ],
    ),
    StandardDef(
        code="CA_OHS",
        standard_class="hybrid",
        title_fa="الزامات ایمنی استانی / OHS کانادا",
        title_en="Canadian provincial OHS / construction safety",
        title_de="Arbeitsschutz Kanada (provinziell)",
        publisher="Provincial regulators",
        country_home=CountryCode.CA,
        check_keywords=["OHS", "health and safety", "WSIB"],
        applicability=[
            StandardApplicability(CountryCode.CA, None, "recommended_default"),
        ],
    ),
    # ---- Global / FIDIC (optional across countries) ----
    StandardDef(
        code="FIDIC_RED",
        standard_class="contractual",
        title_fa="FIDIC Red Book — شرایط پیمان ساخت",
        title_en="FIDIC Red Book — Construction",
        title_de="FIDIC Red Book — Bauvertrag",
        publisher="FIDIC",
        country_home=None,
        check_keywords=["FIDIC", "Employer", "Engineer", "Contractor"],
        applicability=[
            StandardApplicability(CountryCode.IR, _CIVIL, "optional"),
            StandardApplicability(CountryCode.DE, _CIVIL, "optional"),
            StandardApplicability(CountryCode.CA, _CIVIL, "optional"),
            StandardApplicability(CountryCode.EU, None, "recommended_default"),
        ],
    ),
]


def get_standard(code: str) -> StandardDef | None:
    for s in STANDARDS_CATALOG:
        if s.code == code:
            return s
    return None


def list_standards_for_country(country: CountryCode) -> list[StandardDef]:
    out: list[StandardDef] = []
    for s in STANDARDS_CATALOG:
        if any(a.country == country for a in s.applicability):
            out.append(s)
    return out


def applicability_level(
    standard: StandardDef, country: CountryCode, project_type: str | ProjectType | None
) -> str | None:
    """Return applicability level if standard is listed for country; else None."""
    ptype = project_type.value if isinstance(project_type, ProjectType) else (project_type or "")
    matched: str | None = None
    for a in standard.applicability:
        if a.country != country:
            continue
        if a.project_types is None or ptype in a.project_types:
            # Prefer more specific / stronger level if multiple match
            if matched is None or _level_rank(a.level) > _level_rank(matched):
                matched = a.level
    return matched


def _level_rank(level: str) -> int:
    return {"optional": 1, "recommended_default": 2, "mandatory_default": 3}.get(level, 0)


def should_auto_select(level: str | None) -> bool:
    return level in {"mandatory_default", "recommended_default"}


def default_selection_plan(
    country: CountryCode, project_type: str | ProjectType | None
) -> list[tuple[StandardDef, str, bool]]:
    """
    Returns (standard, applicability_level, is_selected_default) for all
    standards visible for this country.
    """
    plan: list[tuple[StandardDef, str, bool]] = []
    for s in list_standards_for_country(country):
        level = applicability_level(s, country, project_type) or "optional"
        plan.append((s, level, should_auto_select(level)))
    return plan
