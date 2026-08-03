"""Risk Knowledge Base (RKB) — DB-backed with Python seed dict fallback.

Phase 6: when settings.rkb_db_enabled, rule runners resolve Risk IDs from the
`risks` table; otherwise they fall back to NEW_RISK_IDS_BATCH1/2 dicts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.knowledge.seed_rules_batch1 import NEW_RISK_IDS_BATCH1
from app.knowledge.seed_rules_batch2 import NEW_RISK_IDS_BATCH2
from app.models import Risk

logger = logging.getLogger(__name__)

# Default mitigations by category (used when seeding; admin-editable later)
_DEFAULT_MITIGATION: dict[str, str] = {
    "delay": "Require a corrected baseline programme and clarifying addendum before award.",
    "claim": "Clarify contractual wording and issue written Q&A / addendum allocating responsibility.",
    "cost": "Reconcile quantities/units across BOQ, drawings, and contract before tender close.",
    "compliance": "Bind the correct StandardVersion and evidence compliance against StandardClauses.",
    "quality": "Specify measurable grades/acceptance criteria; reject vague performance language.",
    "commercial": "Fix bond/payment security terms to a single enforceable formulation.",
    "constructability": "Obtain missing geotech/design inputs and align drawings with site data.",
    "procurement": "Confirm long-lead items and evaluation criteria are published with weights.",
    "safety": "Ensure fire/life-safety requirements are explicit and consistent across docs.",
}

_DEFAULT_MITIGATION_I18N: dict[str, dict[str, str]] = {
    "delay": {
        "fa": "قبل از ابلاغ، برنامه مبنای اصلاح‌شده و الحاقیه شفاف‌سازی الزامی است.",
        "de": "Vor Zuschlag korrigiertes Basisprogramm und klarstellendes Addendum verlangen.",
        "fr": "Exiger un programme de référence corrigé et un addendum de clarification avant attribution.",
    },
    "claim": {
        "fa": "متن قراردادی را شفاف کنید و با پرسش‌وپاسخ/الحاقیه مسئولیت را تخصیص دهید.",
        "de": "Vertragswortlaut klären und Verantwortung per Q&A/Addendum zuweisen.",
        "fr": "Clarifier le libellé contractuel et allouer la responsabilité via Q&R/addendum.",
    },
    "cost": {
        "fa": "قبل از پایان مناقصه، مقادیر/واحدها را بین BOQ، نقشه و پیمان هم‌راستا کنید.",
        "de": "Mengen/Einheiten vor Fristende über BOQ, Pläne und Vertrag abstimmen.",
        "fr": "Réconcilier quantités/unités entre BOQ, plans et contrat avant clôture.",
    },
    "compliance": {
        "fa": "نسخه صحیح استاندارد را متصل کنید و انطباق با بندها را مستند کنید.",
        "de": "Korrekte StandardVersion binden und Konformität zu Klauseln nachweisen.",
        "fr": "Lier la bonne StandardVersion et evidencer la conformité aux clauses.",
    },
    "quality": {
        "fa": "رده‌ها و معیار پذیرش قابل اندازه‌گیری تعریف کنید؛ زبان مبهم را حذف کنید.",
        "de": "Messbare Güten/Abnahmekriterien festlegen; vage Formulierungen ablehnen.",
        "fr": "Définir grades/critères d'acceptation mesurables; rejeter le flou.",
    },
    "commercial": {
        "fa": "شرایط ضمانت/پرداخت را به یک فرمول واحد و لازم‌الاجرا برسانید.",
        "de": "Garantie-/Zahlungskonditionen auf eine durchsetzbare Formulierung vereinheitlichen.",
        "fr": "Unifier les conditions de caution/paiement en une formulation exécutoire.",
    },
    "constructability": {
        "fa": "ورودی‌های ژئوتکنیک/طراحی ناقص را تکمیل و نقشه‌ها را با داده سایت هم‌راستا کنید.",
        "de": "Fehlende Geotechnik-/Designinputs beschaffen und Pläne mit Standortdaten abstimmen.",
        "fr": "Compléter les entrées géotech/conception et aligner les plans sur le site.",
    },
    "procurement": {
        "fa": "اقلام با زمان تدارک طولانی و معیارهای ارزیابی وزن‌دار را منتشر کنید.",
        "de": "Long-Lead-Positionen und gewichtete Zuschlagskriterien veröffentlichen.",
        "fr": "Publier les postes long-délai et les critères d'évaluation pondérés.",
    },
    "safety": {
        "fa": "الزامات ایمنی/حریق را در اسناد صریح و یکدست کنید.",
        "de": "Brand-/Lebenssicherheitsanforderungen klar und konsistent machen.",
        "fr": "Rendre explicites et cohérentes les exigences incendie/sécurité.",
    },
}

_DEFAULT_RELATED_DOCS: dict[str, list[str]] = {
    "RISK-SCHED": ["Construction Schedule", "Contract Documents"],
    "RISK-CON": ["Contract Documents", "Tender Documents"],
    "RISK-SPEC": ["Technical Specifications", "Engineering Drawings"],
    "RISK-BOQ": ["Bill of Quantities (BOQ)", "Engineering Drawings"],
    "RISK-DRAW": ["Engineering Drawings"],
    "RISK-TEN": ["Tender Documents", "Construction Schedule"],
    "RISK-STD": ["Standards and Codes"],
    "RISK-GEO": ["Geotechnical Reports", "Engineering Drawings"],
    "RISK-REQ": ["Employer Requirements", "Technical Specifications"],
    "RISK-ADD": ["Addenda", "Tender Documents"],
}


def all_seed_risk_dicts() -> list[dict[str, Any]]:
    """Canonical 46 seed Risk ID dicts (Batches 1–2). Preserved as fallback."""
    out: list[dict[str, Any]] = []
    for row in NEW_RISK_IDS_BATCH1:
        item = dict(row)
        item["seed_batch"] = 1
        out.append(item)
    for row in NEW_RISK_IDS_BATCH2:
        item = dict(row)
        item["seed_batch"] = 2
        out.append(item)
    return out


def python_risk_catalog() -> dict[str, dict[str, Any]]:
    """risk_id → enriched dict (fallback when RKB_DB_ENABLED is off)."""
    catalog: dict[str, dict[str, Any]] = {}
    for row in all_seed_risk_dicts():
        rid = str(row["risk_id"])
        catalog[rid] = _enrich_seed_row(row)
    return catalog


def _enrich_seed_row(row: dict[str, Any]) -> dict[str, Any]:
    rid = str(row["risk_id"])
    category = str(row.get("category") or "claim")
    related_docs: list[str] = []
    for prefix, docs in _DEFAULT_RELATED_DOCS.items():
        if rid.startswith(prefix):
            related_docs = list(docs)
            break
    # Probability prior from impact severity
    impacts = [
        str(row.get("cost_impact") or "medium"),
        str(row.get("schedule_impact") or "medium"),
        str(row.get("quality_impact") or "medium"),
    ]
    rank = {"low": 1, "medium": 2, "high": 3}
    avg = sum(rank.get(i, 2) for i in impacts) / 3
    probability = "high" if avg >= 2.5 else ("low" if avg < 1.5 else "medium")
    return {
        "risk_id": rid,
        "category": category,
        "description": str(row.get("description") or ""),
        "probability": probability,
        "cost_impact": row.get("cost_impact"),
        "schedule_impact": row.get("schedule_impact"),
        "quality_impact": row.get("quality_impact"),
        "safety_impact": row.get("safety_impact") or "low",
        "mitigation": row.get("mitigation") or _DEFAULT_MITIGATION.get(category),
        "lessons_learned": row.get("lessons_learned"),
        "related_standards": row.get("related_standards") or [],
        "related_documents": row.get("related_documents") or related_docs,
        "seed_batch": row.get("seed_batch"),
        "version": int(row.get("version") or 1),
        "is_active": bool(row.get("is_active", True)),
        "source": "python_seed",
    }


def risk_to_dict(risk: Risk) -> dict[str, Any]:
    def _loads(raw: str | None) -> list[Any]:
        if not raw:
            return []
        try:
            val = json.loads(raw)
            return val if isinstance(val, list) else []
        except json.JSONDecodeError:
            return []

    return {
        "id": risk.id,
        "risk_id": risk.risk_id,
        "category": risk.category,
        "description": risk.description,
        "probability": risk.probability,
        "cost_impact": risk.cost_impact,
        "schedule_impact": risk.schedule_impact,
        "quality_impact": risk.quality_impact,
        "safety_impact": risk.safety_impact,
        "mitigation": risk.mitigation,
        "lessons_learned": risk.lessons_learned,
        "related_standards": _loads(risk.related_standards_json),
        "related_documents": _loads(risk.related_documents_json),
        "seed_batch": risk.seed_batch,
        "version": risk.version,
        "is_active": risk.is_active,
        "source": "database",
    }


async def seed_risks_table(session: AsyncSession, *, overwrite_empty_fields: bool = False) -> dict[str, int]:
    """Insert missing seed Risk IDs into `risks`. Never deletes. Returns counts."""
    seeds = all_seed_risk_dicts()
    existing = {
        r.risk_id: r
        for r in (await session.execute(select(Risk))).scalars().all()
    }
    inserted = 0
    skipped = 0
    for raw in seeds:
        enriched = _enrich_seed_row(raw)
        rid = enriched["risk_id"]
        if rid in existing:
            skipped += 1
            if overwrite_empty_fields:
                row = existing[rid]
                if not row.mitigation and enriched.get("mitigation"):
                    row.mitigation = enriched["mitigation"]
                if not row.related_documents_json and enriched.get("related_documents"):
                    row.related_documents_json = json.dumps(
                        enriched["related_documents"], ensure_ascii=False
                    )
            continue
        session.add(
            Risk(
                risk_id=rid,
                category=enriched["category"],
                description=enriched["description"],
                probability=enriched["probability"],
                cost_impact=enriched.get("cost_impact"),
                schedule_impact=enriched.get("schedule_impact"),
                quality_impact=enriched.get("quality_impact"),
                safety_impact=enriched.get("safety_impact") or "low",
                mitigation=enriched.get("mitigation"),
                lessons_learned=enriched.get("lessons_learned"),
                related_standards_json=json.dumps(
                    enriched.get("related_standards") or [], ensure_ascii=False
                ),
                related_documents_json=json.dumps(
                    enriched.get("related_documents") or [], ensure_ascii=False
                ),
                seed_batch=enriched.get("seed_batch"),
                version=1,
                is_active=True,
            )
        )
        inserted += 1
    await session.commit()
    total = (await session.execute(select(Risk))).scalars().all()
    return {
        "seed_dicts": len(seeds),
        "inserted": inserted,
        "skipped_existing": skipped,
        "table_count": len(total),
        "unique_seed_ids": len({s["risk_id"] for s in seeds}),
    }


async def get_risk_by_id(
    risk_id: str,
    *,
    db: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """
    Resolve a Risk ID. When RKB_DB_ENABLED and db provided → DB first.
    Always falls back to Python seed catalog if missing/disabled.
    """
    rid = (risk_id or "").strip()
    if not rid:
        return None

    if settings.rkb_db_enabled and db is not None:
        row = (
            await db.execute(select(Risk).where(Risk.risk_id == rid, Risk.is_active.is_(True)))
        ).scalar_one_or_none()
        if row is not None:
            return risk_to_dict(row)

    return python_risk_catalog().get(rid)


async def list_risks_from_db(db: AsyncSession, *, active_only: bool = True) -> list[dict[str, Any]]:
    stmt = select(Risk).order_by(Risk.risk_id)
    if active_only:
        stmt = stmt.where(Risk.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [risk_to_dict(r) for r in rows]


def list_risks_from_python() -> list[dict[str, Any]]:
    return list(python_risk_catalog().values())


async def load_rkb_catalog_for_runners(db: AsyncSession | None) -> dict[str, dict[str, Any]] | None:
    """
    Snapshot for rule runners when RKB_DB_ENABLED.
    Returns None when flag is off (runners use Python seed dicts).
    """
    if not settings.rkb_db_enabled or db is None:
        return None
    rows = await list_risks_from_db(db, active_only=True)
    catalog: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        item["mapping_source"] = "rkb_db"
        catalog[str(item["risk_id"])] = item
    # Fill any seed IDs missing from DB so runners never lose mappings
    for rid, seed in python_risk_catalog().items():
        if rid not in catalog:
            fallback = dict(seed)
            fallback["mapping_source"] = "python_seed_fallback"
            catalog[rid] = fallback
    return catalog


async def resolve_risk_for_rule(
    *,
    rule_code: str,
    logic_config: dict[str, Any] | None,
    db: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """Look up RKB record for a seed rule's risk_id (DB when enabled, else Python)."""
    cfg = logic_config or {}
    risk_id = str(cfg.get("risk_id") or "").strip()
    if not risk_id:
        return None
    record = await get_risk_by_id(risk_id, db=db)
    if record is None:
        logger.warning("Risk ID %s for rule %s not found in RKB", risk_id, rule_code)
        return {
            "risk_id": risk_id,
            "category": cfg.get("validation_category") or "claim",
            "description": "",
            "source": "missing",
            "rule_code": rule_code,
        }
    out = dict(record)
    out["rule_code"] = rule_code
    out["mapping_source"] = "rkb_db" if settings.rkb_db_enabled and record.get("source") == "database" else "python_seed"
    return out


def apply_rkb_to_finding_fields(
    *,
    risk: dict[str, Any] | None,
    financial_impact: str | None,
    schedule_impact: str | None,
    recommendation: str | None,
    lang: Any | None = None,
) -> dict[str, Any]:
    """Enrich finding impact/recommendation from RKB defaults when missing."""
    lang_code = getattr(lang, "value", None) or (str(lang).lower() if lang else "en")
    if lang_code not in {"fa", "en", "de", "fr"}:
        lang_code = "en"

    def _mitigation_for(category: str | None) -> str | None:
        if not category:
            return None
        if lang_code != "en":
            localized = _DEFAULT_MITIGATION_I18N.get(category, {}).get(lang_code)
            if localized:
                return localized
        return _DEFAULT_MITIGATION.get(category)

    if not risk:
        return {
            "financial_impact": financial_impact,
            "schedule_impact": schedule_impact,
            "recommendation": recommendation,
            "risk_id": None,
        }
    fallback = (
        recommendation
        or risk.get("mitigation")
        or _mitigation_for(risk.get("category"))
        or {
            "fa": "راهنمای کاهش ریسک را در پایگاه دانش ریسک ببینید.",
            "de": "Siehe Minderungsempfehlung in der Risk Knowledge Base.",
            "fr": "Voir la mitigation dans la Risk Knowledge Base.",
            "en": "See Risk Knowledge Base mitigation guidance.",
        }.get(lang_code, "See Risk Knowledge Base mitigation guidance.")
    )
    # Prefer already-localized recommendation from the rule; only inject RKB English
    # mitigation when recommendation is empty or still the English stub.
    rec = recommendation
    if not rec or rec.strip().lower().startswith("see finding recommendation"):
        rec = fallback
    return {
        "financial_impact": financial_impact or risk.get("cost_impact"),
        "schedule_impact": schedule_impact or risk.get("schedule_impact"),
        "recommendation": rec,
        "risk_id": risk.get("risk_id"),
        "rkb_category": risk.get("category"),
        "rkb_probability": risk.get("probability"),
        "rkb_mitigation": risk.get("mitigation"),
        "mapping_source": risk.get("mapping_source") or risk.get("source"),
    }
