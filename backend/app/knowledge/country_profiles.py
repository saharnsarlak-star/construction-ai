"""Country profiles — analysis configuration as DATA (not hardcoded if/else in UI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import CountryCode, ProjectType


@dataclass(frozen=True)
class CountryProfile:
    code: str
    country: CountryCode
    version: int
    currency: str
    primary_standards_system: str
    legal_contract_framework: str
    measurement_conventions: str
    default_ruleset_code: str
    default_locales: tuple[str, ...]
    config: dict[str, Any] = field(default_factory=dict)


COUNTRY_PROFILES: dict[CountryCode, CountryProfile] = {
    CountryCode.IR: CountryProfile(
        code="IR_PROFILE_V1",
        country=CountryCode.IR,
        version=1,
        currency="IRR",
        primary_standards_system="IR_NBR_FEHREST",
        legal_contract_framework="Iran public tender + General/Particular Conditions of Contract",
        measurement_conventions="Metric; Fehrest Baha / Iranian BoQ culture",
        default_ruleset_code="IR_CORE_V1",
        default_locales=("fa", "en"),
        config={
            "boq_format": "fehrest_baha",
            "contract_keywords_hint": ["شرایط عمومی", "شرایط خصوصی", "تعدیل", "فهرست بها"],
        },
    ),
    CountryCode.DE: CountryProfile(
        code="DE_PROFILE_V1",
        country=CountryCode.DE,
        version=1,
        currency="EUR",
        primary_standards_system="DE_VOB_DIN",
        legal_contract_framework="VOB/B + BGB construction contract practice",
        measurement_conventions="Metric; GAEB / Leistungsverzeichnis culture",
        default_ruleset_code="DE_CORE_V1",
        default_locales=("de", "en"),
        config={
            "boq_format": "gaeb",
            "contract_keywords_hint": ["VOB/B", "BGB", "Leistungsbeschreibung", "Nachtrag"],
        },
    ),
    CountryCode.CA: CountryProfile(
        code="CA_PROFILE_V1",
        country=CountryCode.CA,
        version=1,
        currency="CAD",
        primary_standards_system="CA_NBC_CSA_CCDC",
        legal_contract_framework="CCDC forms + provincial practice; NBC/CSA references",
        measurement_conventions="Metric (soft metric common); trade BoQ / unit-price",
        default_ruleset_code="CA_CORE_V1",
        default_locales=("en", "fr"),
        config={
            "boq_format": "trade_boq",
            "contract_keywords_hint": ["CCDC", "holdback", "change order", "NBC"],
        },
    ),
    CountryCode.EU: CountryProfile(
        code="EU_PROFILE_V1",
        country=CountryCode.EU,
        version=1,
        currency="EUR",
        primary_standards_system="EU_DIRECTIVES_EN_STANDARDS",
        legal_contract_framework="EU procurement directives + member-state overlays (use DE/CA/IR when known)",
        measurement_conventions="Metric; EN standards; FIDIC often used cross-border",
        default_ruleset_code="EU_CORE_V1",
        default_locales=("en", "de", "fr"),
        config={
            "boq_format": "generic_en",
            "contract_keywords_hint": ["FIDIC", "EN ", "procurement"],
        },
    ),
}


def get_country_profile(country: CountryCode) -> CountryProfile:
    return COUNTRY_PROFILES.get(country, COUNTRY_PROFILES[CountryCode.IR])


def profile_snapshot(country: CountryCode, project_type: ProjectType | None = None) -> dict[str, Any]:
    p = get_country_profile(country)
    return {
        "code": p.code,
        "country": p.country.value,
        "version": p.version,
        "currency": p.currency,
        "primary_standards_system": p.primary_standards_system,
        "legal_contract_framework": p.legal_contract_framework,
        "measurement_conventions": p.measurement_conventions,
        "default_ruleset_code": p.default_ruleset_code,
        "project_type": (project_type or ProjectType.INFRASTRUCTURE).value,
        "config": p.config,
    }
