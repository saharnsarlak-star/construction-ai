"""OpenAI-compatible Chat Completions client (httpx). No provider was pre-configured."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Approximate USD per 1M tokens for gpt-4o-mini (list price; adjust via env later)
_DEFAULT_INPUT_PER_M = 0.15
_DEFAULT_OUTPUT_PER_M = 0.60


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    model: str = ""
    provider: str = ""


@dataclass
class LLMResponse:
    content: str
    parsed: dict[str, Any] | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: dict[str, Any] | None = None


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMClient:
    """Chat Completions against OpenAI or any OpenAI-compatible base URL."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        replay_path: str | Path | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.base_url = (base_url or settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model or settings.llm_model or "gpt-4o-mini"
        self.provider = (provider or settings.llm_provider or "openai_compatible").lower()
        self.replay_path = Path(replay_path or settings.llm_replay_path or "") if (
            replay_path or settings.llm_replay_path
        ) else None
        self._replay_store: dict[str, Any] = {}
        if self.provider == "replay" and self.replay_path and self.replay_path.exists():
            try:
                self._replay_store = json.loads(self.replay_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._replay_store = {}

    @property
    def is_configured(self) -> bool:
        if self.provider == "replay":
            return bool(self._replay_store) or (self.replay_path is not None)
        if self.provider == "local_semantic":
            return True
        return bool(self.api_key)

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        call_key: str | None = None,
        temperature: float = 0.1,
        timeout_s: float = 60.0,
    ) -> LLMResponse:
        if self.provider == "replay":
            return self._replay(call_key or _hash_key(system, user), system=system, user=user)

        if self.provider == "local_semantic":
            return _local_semantic_respond(system=system, user=user, call_key=call_key or "unknown")

        if not self.api_key:
            raise LLMNotConfiguredError(
                "No LLM API key configured. Set OPENAI_API_KEY (OpenAI-compatible Chat Completions). "
                "This project had no LLM provider configured before Phase 4."
            )

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        t0 = time.perf_counter()
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        latency_ms = (time.perf_counter() - t0) * 1000.0
        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()
        usage_raw = data.get("usage") or {}
        pt = int(usage_raw.get("prompt_tokens") or 0)
        ct = int(usage_raw.get("completion_tokens") or 0)
        cost = (pt / 1_000_000.0) * _DEFAULT_INPUT_PER_M + (ct / 1_000_000.0) * _DEFAULT_OUTPUT_PER_M
        usage = LLMUsage(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            latency_ms=round(latency_ms, 1),
            estimated_cost_usd=round(cost, 6),
            model=self.model,
            provider=self.provider,
        )
        parsed = _safe_json(content)
        return LLMResponse(content=content, parsed=parsed, usage=usage, raw=data)

    def chat_vision_json(
        self,
        *,
        system: str,
        user_text: str,
        image_b64: str,
        call_key: str | None = None,
        temperature: float = 0.1,
        timeout_s: float = 90.0,
        mime: str = "image/png",
    ) -> LLMResponse:
        """Multimodal Chat Completions (vision). Falls back to replay/local_semantic text path."""
        if self.provider == "replay":
            return self._replay(call_key or "vision_default", system=system, user=user_text)
        if self.provider == "local_semantic":
            return _local_semantic_respond(system=system, user=user_text, call_key=call_key or "vision")

        if not self.api_key:
            raise LLMNotConfiguredError(
                "No LLM API key for vision. Set OPENAI_API_KEY or use LLM_PROVIDER=replay."
            )

        url = f"{self.base_url}/chat/completions"
        vision_model = getattr(settings, "vision_llm_model", None) or self.model
        payload = {
            "model": vision_model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                        },
                    ],
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        t0 = time.perf_counter()
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        latency_ms = (time.perf_counter() - t0) * 1000.0
        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()
        usage_raw = data.get("usage") or {}
        pt = int(usage_raw.get("prompt_tokens") or 0)
        ct = int(usage_raw.get("completion_tokens") or 0)
        cost = (pt / 1_000_000.0) * _DEFAULT_INPUT_PER_M + (ct / 1_000_000.0) * _DEFAULT_OUTPUT_PER_M
        usage = LLMUsage(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            latency_ms=round(latency_ms, 1),
            estimated_cost_usd=round(cost, 6),
            model=str(vision_model),
            provider=self.provider,
        )
        parsed = _safe_json(content)
        return LLMResponse(content=content, parsed=parsed, usage=usage, raw=data)

    def _replay(self, key: str, *, system: str, user: str) -> LLMResponse:
        entry = self._replay_store.get(key) or self._replay_store.get("default")
        if entry is None:
            # Fall through: match by rule code prefix in key
            for k, v in self._replay_store.items():
                if k != "default" and key.startswith(k):
                    entry = v
                    break
        if entry is None:
            raise LLMNotConfiguredError(f"Replay store has no entry for key={key!r}")
        content = entry if isinstance(entry, str) else json.dumps(entry.get("content") or entry, ensure_ascii=False)
        if isinstance(entry, dict) and "content" in entry and isinstance(entry["content"], dict):
            content = json.dumps(entry["content"], ensure_ascii=False)
        parsed = _safe_json(content) if isinstance(content, str) else entry
        usage_meta = entry.get("usage") if isinstance(entry, dict) else {}
        usage = LLMUsage(
            prompt_tokens=int((usage_meta or {}).get("prompt_tokens") or 0),
            completion_tokens=int((usage_meta or {}).get("completion_tokens") or 0),
            total_tokens=int((usage_meta or {}).get("total_tokens") or 0),
            latency_ms=float((usage_meta or {}).get("latency_ms") or 0),
            estimated_cost_usd=float((usage_meta or {}).get("estimated_cost_usd") or 0),
            model=str((usage_meta or {}).get("model") or "replay"),
            provider="replay",
        )
        return LLMResponse(content=content if isinstance(content, str) else json.dumps(content), parsed=parsed if isinstance(parsed, dict) else None, usage=usage)


def _safe_json(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        # try extract fenced block
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def _hash_key(system: str, user: str) -> str:
    import hashlib

    return hashlib.sha256(f"{system}\n---\n{user}".encode("utf-8")).hexdigest()[:16]


def _ti_local_semantic_coverage(tender_excerpt: str, requirement_text: str) -> dict[str, Any]:
    """
    Offline meaning-based TI-1 check for LLM_PROVIDER=local_semantic.

    Uses obligation presence in tender excerpt — not keyword overlap on standard name.
    """
    import re

    tender = (tender_excerpt or "").strip()
    req = (requirement_text or "").strip()
    if not req:
        return {"coverage_status": "covered", "severity": "low", "reasoning": "Empty requirement", "tender_excerpt": None}

    # Extract numeric obligations from requirement for meaning anchor
    nums = re.findall(r"\d+(?:\.\d+)?", req)
    tender_lower = tender.lower()
    req_lower = req.lower()

    if re.search(r"\b(contradict|conflict|must not|shall not|نباید|ممنوع)\b", tender, re.I):
        if any(tok in tender_lower for tok in ("fire", "حریق", "rating", "minimum", "حداقل")):
            return {
                "coverage_status": "contradictory",
                "severity": "high",
                "reasoning": "Tender text appears to conflict with the standard obligation (offline semantic).",
                "tender_excerpt": tender[:400] or None,
            }

    if len(tender) < 100:
        return {
            "coverage_status": "silent",
            "severity": "high",
            "reasoning": "Tender documents do not substantively address this standard obligation.",
            "tender_excerpt": tender[:200] or None,
        }

    # Partial: mentions domain keywords but missing numeric obligation
    domain_hits = sum(
        1
        for tok in ("wall", "fire", "corridor", "راهرو", "حریق", "سقف", "minimum", "حداقل")
        if tok in tender_lower or tok in req_lower
    )
    if domain_hits >= 1 and nums:
        num_covered = any(n in tender for n in nums[:3])
        if not num_covered:
            return {
                "coverage_status": "partial",
                "severity": "medium",
                "reasoning": "Tender mentions related topic but omits key measurable parameters from the requirement.",
                "tender_excerpt": tender[:400],
            }

    return {
        "coverage_status": "covered",
        "severity": "low",
        "reasoning": "Tender appears to address the obligation (offline semantic).",
        "tender_excerpt": tender[:200] or None,
    }


def _local_semantic_respond(*, system: str, user: str, call_key: str) -> LLMResponse:
    """
    Offline semantic responder for Phase 4 when no cloud LLM key exists.

    Not a substitute for production LLM — used only when LLM_PROVIDER=local_semantic.
    Produces structured JSON using the same excerpt/discrepancy payload the live model receives.
    """
    import re
    import time

    t0 = time.perf_counter()
    try:
        payload = json.loads(user)
    except json.JSONDecodeError:
        payload = {}

    # Phase C / TI-1 — offline semantic compliance (local_semantic provider)
    if payload.get("task") == "semantic_standard_compliance_check":
        tender = str(payload.get("tender_excerpt") or "").strip()
        req_text = str((payload.get("requirement") or {}).get("text") or "").strip()
        content = _ti_local_semantic_coverage(tender, req_text)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return LLMResponse(
            content=json.dumps(content, ensure_ascii=False),
            parsed=content,
            usage=LLMUsage(latency_ms=round(latency_ms, 1), model="local_semantic", provider="local_semantic"),
        )

    mode = str(payload.get("mode") or "")
    rule = payload.get("rule") or {}
    excerpts = payload.get("excerpts") or []
    code = str(rule.get("code") or call_key)

    def first_quote(*patterns: str) -> tuple[str, str, str]:
        for ex in excerpts:
            text = str(ex.get("text") or "")
            for pat in patterns:
                if re.search(pat, text, re.I):
                    # prefer the matching sentence
                    for sent in re.split(r"(?<=[.:;])\s+", text):
                        if re.search(pat, sent, re.I):
                            return sent.strip()[:500], str(ex.get("document") or ""), str(ex.get("location") or "")
                    return text[:400], str(ex.get("document") or ""), str(ex.get("location") or "")
        if excerpts:
            ex = excerpts[0]
            return str(ex.get("text") or "")[:400], str(ex.get("document") or ""), str(ex.get("location") or "")
        return "", "", ""

    content: dict[str, Any]
    if mode == "hybrid_explain":
        summary = str(payload.get("python_discrepancy_summary") or "")
        evidence = str(payload.get("python_evidence") or "")
        quote, doc, loc = first_quote(r".+")
        content = {
            "triggered": True,
            "confidence_score": 82,
            "title": str(rule.get("title") or code),
            "description": (
                f"Python detected: {summary}. This creates claim/delay exposure because tender "
                f"parties may rely on inconsistent baselines. Evidence: {evidence}."
            ),
            "recommendation": (
                "Reconcile the conflicting values before bid submission and issue a clarifying addendum "
                "stating which document governs."
            ),
            "source_excerpt": quote or evidence[:400],
            "document_name": doc or "hybrid",
            "location": loc or "python_discrepancy",
            "reasoning": "HYBRID path: LLM/local explainer did not re-detect; explained Python discrepancy only.",
        }
    else:
        # AI detect — rule-specific semantic triggers
        check = str(rule.get("check") or "")
        triggered = False
        conf = 70
        title = str(rule.get("title") or code)
        description = str(rule.get("description") or "")
        recommendation = "Clarify ambiguous wording with measurable criteria before award."
        quote, doc, loc = "", "", ""
        reasoning = ""

        if check == "contract_responsibility_ambiguity":
            quote, doc, loc = first_quote(r"if necessary", r"as required", r"reasonable endeavou?rs")
            if quote:
                triggered = True
                conf = 88
                description = (
                    "Clause allocates drainage/work using non-measurable language ('if necessary' / similar), "
                    "leaving Employer vs Contractor responsibility ambiguous and claim-prone."
                )
                recommendation = (
                    "Replace 'if necessary' with objective triggers (e.g. rainfall intensity, geotech water table) "
                    "and name the responsible party explicitly."
                )
                reasoning = "Ambiguous modality without acceptance criteria for drainage obligation."
        elif check == "contract_bond_ambiguity":
            quote, doc, loc = first_quote(r"bond", r"guarantee", r"performance security")
            # contradicting percentages in same pack
            all_text = "\n".join(str(e.get("text") or "") for e in excerpts)
            pcts = re.findall(r"(\d{1,2})\s*%\s*(?:performance\s+)?(?:bond|guarantee|security)", all_text, re.I)
            if quote and (len(set(pcts)) > 1 or re.search(r"may\s+be\s+waived|or\s+equivalent", all_text, re.I)):
                triggered = True
                conf = 84
                description = (
                    f"Guarantee/bond wording is internally inconsistent or waivable without clear conditions "
                    f"(observed percentages={pcts})."
                )
                recommendation = "State a single mandatory bond percentage, form, and issuer requirements."
                reasoning = "Contradictory or discretionary bond language."
            elif quote:
                triggered = True
                conf = 72
                description = "Bond/guarantee clause present with soft language that may weaken enforceability."
                reasoning = "Soft bond wording detected."
        elif check == "er_vague_performance":
            quote, doc, loc = first_quote(r"high quality", r"world-?class", r"if necessary", r"as required")
            if quote:
                triggered = True
                conf = 86
                description = "Employer Requirement uses vague/unmeasurable performance language."
                recommendation = "Rewrite with measurable KPIs, test methods, and acceptance thresholds."
                reasoning = "Non-measurable performance requirement."
        elif check == "specs_missing_sensitive_grades":
            all_text = "\n".join(str(e.get("text") or "") for e in excerpts)
            has_concrete = re.search(r"\bconcrete\b", all_text, re.I)
            has_grade = re.search(r"\bC\s?\d{2}/\d{2}\b|\bgrade\s*[A-Z0-9]", all_text, re.I)
            if has_concrete and not has_grade:
                quote, doc, loc = first_quote(r"concrete")
                triggered = True
                conf = 80
                description = "Concrete referenced without strength/grade specification."
                recommendation = "Specify concrete grade (e.g. C30/37), exposure class, and cover."
                reasoning = "Sensitive material without grade."
        elif check == "itt_evaluation_unclear":
            quote, doc, loc = first_quote(r"evaluation", r"criteria", r"scoring")
            all_text = "\n".join(str(e.get("text") or "") for e in excerpts)
            if quote and not re.search(r"\b\d{1,3}\s*%", all_text):
                triggered = True
                conf = 78
                description = "Evaluation criteria mentioned without numeric technical/financial weights."
                recommendation = "Publish explicit scoring weights and pass/fail gates."
                reasoning = "Unweighted evaluation criteria."
        elif check in {"geotech_groundwater_content", "addendum_implicit_contradiction", "drawing_missing_connection_detail", "drawing_plan_vs_section"}:
            quote, doc, loc = first_quote(r".{20,}")
            # only trigger groundwater if missing
            if check == "geotech_groundwater_content":
                all_text = "\n".join(str(e.get("text") or "") for e in excerpts)
                if not re.search(r"groundwater|water table", all_text, re.I):
                    triggered = True
                    conf = 75
                    quote = (excerpts[0].get("text") if excerpts else "Geotechnical report excerpt")[:300]
                    doc = excerpts[0].get("document") if excerpts else "geotech"
                    description = "Groundwater table not adequately described in geotechnical excerpts."
                    reasoning = "Missing groundwater content."
                else:
                    triggered = False
            elif check == "addendum_implicit_contradiction":
                quote, doc, loc = first_quote(r"instead", r"replace", r"addendum")
                if quote and not re.search(r"supersed|hereby amends|deletes clause", quote, re.I):
                    triggered = True
                    conf = 77
                    description = "Addendum changes prior requirements without explicit supersession language."
                    reasoning = "Implicit contradiction risk."
            elif check == "drawing_missing_connection_detail":
                all_text = "\n".join(str(e.get("text") or "") for e in excerpts)
                if all_text and not re.search(r"\bconnection\s+detail|\bjoint\s+detail|\brebar\s+lap\b", all_text, re.I):
                    quote, doc, loc = first_quote(r"wall|beam|column|foundation")
                    triggered = True
                    conf = 79
                    description = "Drawing set lacks explicit structural connection/joint detail references."
                    recommendation = "Add connection detail sheets or reference standard detail numbers."
                    reasoning = "Structural elements cited without connection detail callouts."
            elif check == "drawing_plan_vs_section":
                all_text = "\n".join(str(e.get("text") or "") for e in excerpts)
                plan_m = re.search(r"plan[^.\n]{0,40}?(\d+(?:\.\d+)?)\s*m\b", all_text, re.I)
                sect_m = re.search(r"section[^.\n]{0,40}?(\d+(?:\.\d+)?)\s*m\b", all_text, re.I)
                if plan_m and sect_m and plan_m.group(1) != sect_m.group(1):
                    quote = f"plan={plan_m.group(1)}m section={sect_m.group(1)}m"
                    doc = excerpts[0].get("document") if excerpts else "drawing"
                    loc = "plan_vs_section"
                    triggered = True
                    conf = 83
                    description = f"Plan dimension ({plan_m.group(1)}m) conflicts with section ({sect_m.group(1)}m)."
                    recommendation = "Reconcile plan and section dimensions before tender issue."
                    reasoning = "Numeric plan/section mismatch."
            else:
                triggered = False
        else:
            triggered = False

        content = {
            "triggered": triggered,
            "confidence_score": conf if triggered else 0,
            "title": title,
            "description": description,
            "recommendation": recommendation,
            "source_excerpt": quote,
            "document_name": doc,
            "location": loc,
            "reasoning": reasoning or "local_semantic offline provider",
        }

    latency = (time.perf_counter() - t0) * 1000.0
    # Approximate token counts for feasibility reporting
    pt = max(1, len(user) // 4)
    ct = max(1, len(json.dumps(content)) // 4)
    usage = LLMUsage(
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=pt + ct,
        latency_ms=round(latency, 1),
        estimated_cost_usd=0.0,
        model="local_semantic",
        provider="local_semantic",
    )
    return LLMResponse(content=json.dumps(content, ensure_ascii=False), parsed=content, usage=usage)
