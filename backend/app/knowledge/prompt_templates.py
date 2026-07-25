"""AI prompt templates — country-specific LLM context packs (data-driven)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import CountryCode, ProjectType
from app.knowledge.country_profiles import get_country_profile


@dataclass(frozen=True)
class AIPromptTemplate:
    code: str
    country: CountryCode | None
    project_type: ProjectType | None
    parent_code: str | None
    system_prompt: str
    user_prompt_template: str
    context_pack: dict[str, Any] = field(default_factory=dict)
    version: int = 1


PROMPT_TEMPLATES: list[AIPromptTemplate] = [
    AIPromptTemplate(
        code="ANALYZE_RESPONSIBILITY_CLAUSES",
        country=None,
        project_type=None,
        parent_code=None,
        system_prompt=(
            "You are a construction tender risk analyst for the Employer. "
            "Identify unclear responsibility, liability, and duty allocation clauses. "
            "Do not invent statutes; use the provided country context pack."
        ),
        user_prompt_template=(
            "Country profile: {{country_profile}}\n"
            "Context pack: {{context_pack}}\n"
            "Document excerpt:\n{{extracted_text_excerpt}}\n"
            "List unclear responsibility issues with evidence quotes."
        ),
        context_pack={"focus": ["responsibility", "liability", "duty", "indemnity"]},
    ),
    AIPromptTemplate(
        code="ANALYZE_RESPONSIBILITY_CLAUSES",
        country=CountryCode.DE,
        project_type=None,
        parent_code="ANALYZE_RESPONSIBILITY_CLAUSES",
        system_prompt=(
            "Du bist Risikoanalyst für den Auftraggeber (Deutschland). "
            "Prüfe Verantwortlichkeiten unter Bezug auf VOB/B und BGB-Typik. "
            "Nutze die Begriffe Gewährleistung, Verkehrssicherungspflicht, Nachtrag."
        ),
        user_prompt_template=(
            "Länderprofil: {{country_profile}}\n"
            "Kontext: {{context_pack}}\n"
            "Textauszug:\n{{extracted_text_excerpt}}\n"
            "Liste unklare Verantwortlichkeiten mit Zitaten."
        ),
        context_pack={
            "statutes": ["BGB", "VOB/B"],
            "terms": ["Gewährleistung", "Verkehrssicherung", "Nachtrag", "Leistungsbeschreibung"],
        },
    ),
    AIPromptTemplate(
        code="ANALYZE_RESPONSIBILITY_CLAUSES",
        country=CountryCode.IR,
        project_type=None,
        parent_code="ANALYZE_RESPONSIBILITY_CLAUSES",
        system_prompt=(
            "شما تحلیل‌گر ریسک مناقصه از نگاه کارفرما در ایران هستید. "
            "ابهام مسئولیت، تعهدات، تعدیل و شرایط عمومی/خصوصی پیمان را بررسی کنید."
        ),
        user_prompt_template=(
            "پروفایل کشور: {{country_profile}}\n"
            "بسته زمینه: {{context_pack}}\n"
            "متن سند:\n{{extracted_text_excerpt}}\n"
            "ابهامات مسئولیت را با شاهد متنی فهرست کنید."
        ),
        context_pack={
            "statutes": ["شرایط عمومی پیمان", "شرایط خصوصی"],
            "terms": ["مسئولیت", "تعهدات", "تعدیل", "فهرست بها", "دستور کار"],
        },
    ),
    AIPromptTemplate(
        code="ANALYZE_RESPONSIBILITY_CLAUSES",
        country=CountryCode.CA,
        project_type=None,
        parent_code="ANALYZE_RESPONSIBILITY_CLAUSES",
        system_prompt=(
            "You are an employer-side tender risk analyst for Canadian projects. "
            "Focus on CCDC-style responsibility, holdback, and change-order clarity. "
            "Reference NBC/CSA only when present in the context pack."
        ),
        user_prompt_template=(
            "Country profile: {{country_profile}}\n"
            "Context pack: {{context_pack}}\n"
            "Document excerpt:\n{{extracted_text_excerpt}}\n"
            "List unclear responsibility / change allocation issues with quotes."
        ),
        context_pack={
            "statutes": ["CCDC", "NBC", "CSA"],
            "terms": ["holdback", "change order", "GC", "supplementary conditions"],
        },
    ),
]


def resolve_prompt_template(
    *,
    code: str,
    country: CountryCode,
    project_type: ProjectType | None = None,
) -> AIPromptTemplate:
    family = [p for p in PROMPT_TEMPLATES if p.code == code]
    if not family:
        raise KeyError(f"Unknown prompt template code: {code}")

    def score(p: AIPromptTemplate) -> int:
        s = 0
        if p.country == country:
            s += 100
        elif p.country is None:
            s += 10
        else:
            return -1
        if p.project_type is not None and p.project_type == project_type:
            s += 40
        return s

    ranked = [(score(p), p) for p in family if score(p) >= 0]
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def render_prompt_bundle(
    *,
    code: str,
    country: CountryCode,
    project_type: ProjectType | None,
    extracted_text_excerpt: str,
) -> dict[str, Any]:
    tpl = resolve_prompt_template(code=code, country=country, project_type=project_type)
    profile = get_country_profile(country)
    country_profile = {
        "code": profile.code,
        "standards_system": profile.primary_standards_system,
        "legal_framework": profile.legal_contract_framework,
    }
    user = (
        tpl.user_prompt_template.replace("{{country_profile}}", str(country_profile))
        .replace("{{context_pack}}", str(tpl.context_pack))
        .replace("{{extracted_text_excerpt}}", extracted_text_excerpt[:8000])
    )
    return {
        "template_code": tpl.code,
        "country": country.value,
        "resolved_country_scope": tpl.country.value if tpl.country else "global",
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user,
        "context_pack": tpl.context_pack,
    }
