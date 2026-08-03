"""Phase 8 — Vision-assisted drawing checks (DRAW-SEED-002..004).

Rasterizes drawing PDF/image pages (pypdfium2 + Pillow), runs Python vision
heuristics, and optionally a vision-capable LLM when configured.

Feature flag: VISION_DRAWING_CHECKS_ENABLED (default OFF).
Findings use source_layer=vision_based and are advisory evidence-backed checks,
not a replacement for mandatory standards.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.knowledge.seed_rules_batch1 import build_seed_batch1_rules
from app.models import DocumentCategory, LanguageCode, RiskSeverity
from app.services.analyzer import RiskFinding
from app.services.rule_engine.llm_client import LLMClient, LLMNotConfiguredError, LLMUsage

logger = logging.getLogger(__name__)

VISION_CHECKS = {
    "drawing_scale_vs_dimensions",  # DRAW-SEED-002
    "drawing_missing_connection_detail",  # DRAW-SEED-003
    "drawing_plan_vs_section",  # DRAW-SEED-004
}

_VISION_RULES_BY_CHECK = {
    r.logic_config.get("check"): r
    for r in build_seed_batch1_rules()
    if (r.logic_config or {}).get("check") in VISION_CHECKS
}


@dataclass
class RasterPage:
    document_name: str
    page_index: int
    width: int
    height: int
    png_bytes: bytes
    ocr_text: str = ""
    stored_path: str | None = None


@dataclass
class VisionCheckHit:
    check: str
    triggered: bool
    summary: str
    evidence: str
    confidence: int = 60
    excerpts: list[dict[str, str]] = field(default_factory=list)
    method: str = "vision_python"  # vision_python | vision_llm | vision_local


def rasterize_drawing_pages(
    path: str | Path,
    *,
    max_pages: int = 3,
    scale: float = 1.5,
) -> list[RasterPage]:
    """Render PDF (or load image) pages to PNG for vision checks."""
    path = Path(path)
    suffix = path.suffix.lower()
    pages: list[RasterPage] = []
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        try:
            from PIL import Image

            img = Image.open(path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            pages.append(
                RasterPage(
                    document_name=path.name,
                    page_index=0,
                    width=img.width,
                    height=img.height,
                    png_bytes=buf.getvalue(),
                    stored_path=str(path),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vision raster image failed %s: %s", path.name, exc)
        return pages

    if suffix != ".pdf":
        return pages

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        logger.warning("pypdfium2 missing for vision raster: %s", exc)
        return pages

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot open drawing PDF %s: %s", path.name, exc)
        return pages

    n = min(len(pdf), max_pages)
    for i in range(n):
        try:
            page = pdf[i]
            bitmap = page.render(scale=scale)
            pil = bitmap.to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            pages.append(
                RasterPage(
                    document_name=path.name,
                    page_index=i,
                    width=pil.width,
                    height=pil.height,
                    png_bytes=buf.getvalue(),
                    stored_path=str(path),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Raster page %s of %s failed: %s", i, path.name, exc)
    return pages


def ocr_raster_page(page: RasterPage) -> str:
    """Best-effort OCR on a raster page (RapidOCR if available)."""
    if page.ocr_text:
        return page.ocr_text
    try:
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image
        import numpy as np

        engine = RapidOCR()
        img = Image.open(io.BytesIO(page.png_bytes)).convert("RGB")
        result, _ = engine(np.array(img))
        if not result:
            return ""
        texts = [str(row[1]) for row in result if len(row) > 1]
        page.ocr_text = "\n".join(texts)
        return page.ocr_text
    except Exception as exc:  # noqa: BLE001
        logger.info("Vision OCR unavailable/failed: %s", exc)
        return ""


def _python_vision_hits(pages: list[RasterPage], corpus_text: str) -> list[VisionCheckHit]:
    """Deterministic vision/OCR heuristics for the three drawing seed checks."""
    hits: list[VisionCheckHit] = []
    combined = corpus_text or ""
    for p in pages:
        ocr = ocr_raster_page(p)
        if ocr:
            combined += "\n" + ocr

    text = combined
    text_l = text.lower()

    # DRAW-SEED-002 — scale vs dimensions
    scale_m = re.search(r"(?:scale|maßstab|massstab)\s*[:=]?\s*1\s*[:/]\s*(\d+)", text, re.I)
    dims = re.findall(
        r"(\d+(?:[.,]\d+)?)\s*(m|mm|cm)\b",
        text,
        re.I,
    )
    if scale_m:
        scale_den = int(scale_m.group(1))
        unusual = scale_den not in {50, 100, 200, 250, 500, 1000, 1250, 2500}
        # Conflict: title-block says 1:100 but a callout says "SCALE 1:75" also present
        other_scales = {int(x) for x in re.findall(r"1\s*[:/]\s*(\d{2,4})", text)}
        conflict = len(other_scales) >= 2
        if unusual or conflict or (dims and scale_den in {75, 90, 110, 150}):
            hits.append(
                VisionCheckHit(
                    check="drawing_scale_vs_dimensions",
                    triggered=True,
                    summary=(
                        f"Scale inconsistency risk: stated scale 1:{scale_den}"
                        + (f"; multiple scales on sheet {sorted(other_scales)}" if conflict else "")
                        + (f"; {len(dims)} dimension annotations found" if dims else "")
                    ),
                    evidence=f"scale=1:{scale_den}; scales={sorted(other_scales)}; dims={dims[:6]}",
                    confidence=70 if conflict or unusual else 55,
                    excerpts=[{"document": pages[0].document_name if pages else "drawing", "text": scale_m.group(0)}],
                    method="vision_python",
                )
            )

    # DRAW-SEED-003 — missing execution detail for critical connections
    connection_words = re.findall(
        r"\b(connection|anschluss|anschluß|junction|detail|stoß|stoss|node|knoten)\b",
        text_l,
    )
    detail_refs = re.findall(r"\b(?:detail|det\.?)\s*[A-Z0-9\-]+\b", text, re.I)
    see_detail = re.search(r"(?:see\s+detail|siehe\s+detail|ref\.?\s*detail)", text_l)
    missing_marker = re.search(
        r"(?:detail\s+(?:tbd|to\s+follow|later|fehlt|missing)|connection\s+tbd|anschluss\s+fehlt)",
        text_l,
    )
    if (connection_words and not detail_refs and not see_detail) or missing_marker:
        hits.append(
            VisionCheckHit(
                check="drawing_missing_connection_detail",
                triggered=True,
                summary=(
                    "Critical connection/junction referenced without executable detail callout "
                    "(vision/OCR scan of drawing sheet)."
                ),
                evidence=(
                    f"connection_mentions={connection_words[:8]}; detail_refs={detail_refs[:6]}; "
                    f"missing_marker={bool(missing_marker)}"
                ),
                confidence=65 if missing_marker else 55,
                excerpts=[
                    {
                        "document": pages[0].document_name if pages else "drawing",
                        "text": (missing_marker.group(0) if missing_marker else "connection without detail ref"),
                    }
                ],
                method="vision_python",
            )
        )

    # DRAW-SEED-004 — plan vs section contradiction
    has_plan = bool(re.search(r"\b(plan|grundriss|floor\s*plan)\b", text_l))
    has_section = bool(re.search(r"\b(section|schnitt|elevation|ansicht)\b", text_l))
    wall_labels = set(re.findall(r"\b(wall-[a-z0-9]+|w-\d+)\b", text_l))
    # Contradictory height/level statements
    levels = re.findall(r"(?:level|ebene|ffl|okff)\s*[:=]?\s*([+\-]?\d+(?:[.,]\d+)?)", text_l)
    heights = re.findall(r"(?:height|höhe|hoehe|h\s*=)\s*([+\-]?\d+(?:[.,]\d+)?)\s*m?", text_l)
    contradiction_note = re.search(
        r"(?:conflicts?\s+with\s+section|widerspricht\s+(?:dem\s+)?schnitt|"
        r"plan\s+shows?.{0,40}section\s+shows?|section\s+omits?)",
        text_l,
    )
    if (has_plan and has_section and (contradiction_note or (len(set(levels)) >= 2 and wall_labels))) or contradiction_note:
        hits.append(
            VisionCheckHit(
                check="drawing_plan_vs_section",
                triggered=True,
                summary=(
                    "Plan vs section/elevation contradiction indicated on drawing set "
                    "(vision/OCR)."
                ),
                evidence=(
                    f"plan={has_plan}; section={has_section}; levels={levels[:6]}; "
                    f"heights={heights[:6]}; walls={list(wall_labels)[:6]}"
                ),
                confidence=70 if contradiction_note else 58,
                excerpts=[
                    {
                        "document": pages[0].document_name if pages else "drawing",
                        "text": (
                            contradiction_note.group(0)
                            if contradiction_note
                            else f"plan+section present; levels={levels[:4]}"
                        ),
                    }
                ],
                method="vision_python",
            )
        )

    return hits


def _llm_vision_hits(pages: list[RasterPage], client: LLMClient) -> tuple[list[VisionCheckHit], LLMUsage]:
    """Optional vision LLM pass (OpenAI-compatible multimodal)."""
    if not pages:
        return [], LLMUsage()
    page = pages[0]
    b64 = base64.b64encode(page.png_bytes).decode("ascii")
    system = (
        "You are an employer-side construction drawing reviewer. "
        "Inspect the drawing image for: (1) scale vs dimension inconsistency, "
        "(2) missing execution detail for critical connections, "
        "(3) plan vs section/elevation contradiction. "
        "Return ONLY JSON with keys: findings (array of "
        "{check, triggered, summary, evidence, confidence_score, source_excerpt}). "
        f"check must be one of: {sorted(VISION_CHECKS)}. "
        "Only set triggered=true when visual evidence is present."
    )
    user_text = (
        f"Drawing file: {page.document_name} page={page.page_index + 1}. "
        "Inspect the attached IMAGE. "
    )
    if page.ocr_text:
        user_text += "Optional OCR hint (may be incomplete):\n" + page.ocr_text[:800]
    else:
        user_text += "No OCR hint provided — rely only on the image pixels."

    try:
        resp = client.chat_vision_json(
            system=system,
            user_text=user_text,
            image_b64=b64,
            call_key=f"vision:{page.document_name}:{page.page_index}",
        )
    except LLMNotConfiguredError:
        return [], LLMUsage()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vision LLM call failed: %s", exc)
        return [], LLMUsage()

    hits: list[VisionCheckHit] = []
    parsed = resp.parsed or {}
    for row in parsed.get("findings") or []:
        if not isinstance(row, dict) or not row.get("triggered"):
            continue
        check = str(row.get("check") or "")
        if check not in VISION_CHECKS:
            continue
        try:
            conf_i = int(round(float(row.get("confidence_score"))))
            conf_i = max(1, min(100, conf_i))
        except (TypeError, ValueError):
            conf_i = 60
        hits.append(
            VisionCheckHit(
                check=check,
                triggered=True,
                summary=str(row.get("summary") or check),
                evidence=str(row.get("evidence") or ""),
                confidence=conf_i,
                excerpts=[
                    {
                        "document": page.document_name,
                        "text": str(row.get("source_excerpt") or row.get("summary") or "")[:500],
                    }
                ],
                method="vision_llm",
            )
        )
    return hits, resp.usage


def _hit_to_finding(hit: VisionCheckHit, lang: LanguageCode = LanguageCode.EN) -> RiskFinding | None:
    from app.services.analyzer import _impact_label

    rule = _VISION_RULES_BY_CHECK.get(hit.check)
    if rule is None or not hit.triggered:
        return None
    title = rule.title.get(lang) or rule.title.get(LanguageCode.EN) or rule.code
    title_prefix = {
        LanguageCode.FA: "[بینایی]",
        LanguageCode.EN: "[Vision]",
        LanguageCode.DE: "[Vision]",
        LanguageCode.FR: "[Vision]",
    }.get(lang, "[Vision]")
    intro = {
        LanguageCode.FA: f"بررسی نقشه‌ای مبتنی بر بینایی ({hit.method}).",
        LanguageCode.EN: f"VISION-BASED drawing check ({hit.method}).",
        LanguageCode.DE: f"VISION-basierte Planprüfung ({hit.method}).",
        LanguageCode.FR: f"Contrôle de plan basé vision ({hit.method}).",
    }.get(lang, f"VISION-BASED drawing check ({hit.method}).")
    caveat = {
        LanguageCode.FA: "این بررسی مکمل است و جایگزین بازبینی استانداردهای اجباری نیست.",
        LanguageCode.EN: "This supplements — and does not replace — mandatory standards reviews.",
        LanguageCode.DE: "Ergänzend — ersetzt keine verpflichtende Normenprüfung.",
        LanguageCode.FR: "Complément — ne remplace pas la revue normative obligatoire.",
    }.get(lang, "This supplements — and does not replace — mandatory standards reviews.")
    evidence_label = {
        LanguageCode.FA: "شواهد",
        LanguageCode.EN: "Evidence",
        LanguageCode.DE: "Nachweis",
        LanguageCode.FR: "Preuve",
    }.get(lang, "Evidence")
    desc = f"{intro} {hit.summary} {evidence_label}: {hit.evidence}. {caveat}"
    excerpt = (hit.excerpts[0].get("text") if hit.excerpts else hit.evidence) or hit.summary
    rec = rule.recommendation.get(lang) or rule.recommendation.get(LanguageCode.EN) or {
        LanguageCode.FA: "قبل از ابلاغ، مقیاس/جزئیات/مقاطع نقشه را با الحاقیه شفاف کنید.",
        LanguageCode.EN: "Clarify drawing scale/details/sections via addendum before award.",
        LanguageCode.DE: "Maßstab/Details/Schnitte vor Zuschlag per Addendum klären.",
        LanguageCode.FR: "Clarifier échelle/détails/coupes par addendum avant attribution.",
    }.get(lang, "Clarify drawing scale/details/sections via addendum before award.")
    risk_id = (rule.logic_config or {}).get("risk_id")
    from app.services.analyzer import apply_composed_risk

    return apply_composed_risk(
        RiskFinding(
            code=rule.code,
            category=rule.category,
            severity=rule.severity if hit.confidence >= 50 else RiskSeverity.MEDIUM,
            title=f"{title_prefix} {title}",
            description=desc,
            recommendation=rec,
            evidence=f"{hit.excerpts[0].get('document') if hit.excerpts else 'drawing'}: {excerpt}"[:2000],
            finding_category="risk",
            source_excerpt=str(excerpt)[:800],
            cause_effect_chain=[
                f"risk_id={risk_id}",
                f"check={hit.check}",
                "source_layer=vision_based",
                f"vision_method={hit.method}",
                f"confidence_score={hit.confidence}",
                "may_use_vision=true",
                "score_model=likelihood×impact",
            ],
            source_layer="vision_based",
            confidence_score=hit.confidence,
        ),
        likelihood=hit.confidence if hit.confidence is not None else rule.severity,
        financial_impact=rule.financial_impact,
        schedule_impact=rule.schedule_impact,
        lang=lang,
    )


def run_vision_drawing_checks(
    *,
    drawing_docs: list[dict[str, Any]],
    report_language: LanguageCode = LanguageCode.EN,
    llm: LLMClient | None = None,
    max_pages_per_doc: int = 2,
    require_vision_llm: bool = False,
    suppress_ocr_hint: bool = False,
) -> tuple[list[RiskFinding], dict[str, Any]]:
    """
    Execute DRAW-SEED-002..004 vision path when VISION_DRAWING_CHECKS_ENABLED.
    Returns (findings, metrics). Empty when flag is off.

    require_vision_llm=True → fail closed unless a multimodal LLM call succeeds
    (used for validation; production default keeps Python heuristics as fallback).
    suppress_ocr_hint=True → do not send extracted/OCR text to the vision model
    (forces image-only reasoning).
    """
    metrics: dict[str, Any] = {
        "enabled": bool(settings.vision_drawing_checks_enabled),
        "docs_scanned": 0,
        "pages_rasterized": 0,
        "python_hits": 0,
        "llm_hits": 0,
        "findings": 0,
        "vision_llm_called": False,
        "vision_llm_error": None,
    }
    if not settings.vision_drawing_checks_enabled:
        return [], metrics

    client = llm or LLMClient(
        model=getattr(settings, "vision_llm_model", None) or settings.llm_model,
    )
    all_hits: list[VisionCheckHit] = []
    total_usage = LLMUsage(model=client.model, provider=client.provider)

    for doc in drawing_docs:
        path_s = doc.get("stored_path") or ""
        if not path_s or not Path(path_s).exists():
            continue
        name = doc.get("original_name") or Path(path_s).name
        metrics["docs_scanned"] += 1
        pages = rasterize_drawing_pages(path_s, max_pages=max_pages_per_doc)
        for p in pages:
            p.document_name = name
            if suppress_ocr_hint:
                p.ocr_text = ""
        metrics["pages_rasterized"] += len(pages)
        corpus = "" if suppress_ocr_hint else str(doc.get("extracted_text") or "")

        # Multimodal LLM first when configured (real vision path)
        if client.is_configured and client.provider not in {"local_semantic"} and pages:
            metrics["vision_llm_called"] = True
            try:
                llm_hits, usage = _llm_vision_hits(pages, client)
                metrics["llm_hits"] += len(llm_hits)
                total_usage.latency_ms += usage.latency_ms
                total_usage.prompt_tokens += usage.prompt_tokens
                total_usage.completion_tokens += usage.completion_tokens
                total_usage.estimated_cost_usd += usage.estimated_cost_usd
                all_hits.extend(llm_hits)
            except Exception as exc:  # noqa: BLE001
                metrics["vision_llm_error"] = str(exc)
                logger.warning("Vision LLM failed: %s", exc)

        # Python/OCR heuristics as fallback (skipped when validating LLM-only)
        if not require_vision_llm:
            py_hits = _python_vision_hits(pages, corpus)
            metrics["python_hits"] += sum(1 for h in py_hits if h.triggered)
            llm_checks = {h.check for h in all_hits}
            for h in py_hits:
                if h.check not in llm_checks:
                    all_hits.append(h)

    if require_vision_llm and metrics["llm_hits"] == 0:
        metrics["error"] = (
            "require_vision_llm=True but llm_hits=0. "
            "Set OPENAI_API_KEY (OpenAI-compatible vision model, e.g. gpt-4o-mini)."
        )
        return [], metrics

    # Dedupe by check (one finding per check per analysis for Phase 8)
    best: dict[str, VisionCheckHit] = {}
    for h in all_hits:
        if not h.triggered:
            continue
        prev = best.get(h.check)
        if prev is None or h.confidence >= prev.confidence:
            best[h.check] = h

    findings: list[RiskFinding] = []
    for hit in best.values():
        f = _hit_to_finding(hit, report_language)
        if f is not None:
            findings.append(f)
    metrics["findings"] = len(findings)
    metrics["usage"] = {
        "latency_ms": round(total_usage.latency_ms, 1),
        "prompt_tokens": total_usage.prompt_tokens,
        "completion_tokens": total_usage.completion_tokens,
        "estimated_cost_usd": round(total_usage.estimated_cost_usd, 6),
        "model": total_usage.model,
        "provider": total_usage.provider,
    }
    return findings, metrics
