"""Locale-aware obligation modality patterns — country-agnostic validation support."""

from __future__ import annotations

import re
from typing import Literal

LocaleCode = Literal["fa", "en", "de", "auto"]

# Patterns detect obligation markers; used only for post-LLM normalization, not compliance matching.
_MODALITY: dict[str, dict[str, re.Pattern[str]]] = {
    "fa": {
        "mandatory": re.compile(
            r"\b(?:باید|می[\u200c\s]*باید|لازم\s*است|مکلف\s*است)\b"
        ),
        "prohibition": re.compile(
            r"\b(?:نباید|نمی[\u200c\s]*باید|ممنوع\s*است|مجاز\s*نیست)\b"
        ),
        "recommendation": re.compile(
            r"\b(?:توصیه\s*می[\u200c\s]*شود|بهتر\s*است|ترجیح\s*داده\s*می[\u200c\s]*شود)\b"
        ),
    },
    "en": {
        "mandatory": re.compile(
            r"\b(?:shall|must|is required to|are required to|mandatory)\b", re.I
        ),
        "prohibition": re.compile(
            r"\b(?:shall not|must not|is prohibited|are prohibited|forbidden)\b", re.I
        ),
        "recommendation": re.compile(
            r"\b(?:should|recommended|preferably|may consider)\b", re.I
        ),
    },
    "de": {
        "mandatory": re.compile(
            r"\b(?:muss|müssen|ist\s+zu|sind\s+zu|verbindlich)\b", re.I
        ),
        "prohibition": re.compile(
            r"\b(?:darf\s+nicht|dürfen\s+nicht|ist\s+untersagt|verboten)\b", re.I
        ),
        "recommendation": re.compile(
            r"\b(?:sollte|sollten|empfohlen|nach\s+Möglichkeit)\b", re.I
        ),
    },
}


def detect_locale(text: str, hint: str | None = None) -> str:
    if hint and hint in _MODALITY:
        return hint
    if re.search(r"[\u0600-\u06ff]", text or ""):
        return "fa"
    if re.search(r"\b(muss|müssen|soll|DIN|EN\s+\d)\b", text or "", re.I):
        return "de"
    return "en"


def infer_modality(requirement_text: str, current_type: str, *, locale: LocaleCode = "auto") -> str:
    """Return corrected requirement_type based on locale obligation markers."""
    loc = detect_locale(requirement_text, None if locale == "auto" else locale)
    patterns = _MODALITY.get(loc, _MODALITY["en"])
    text = requirement_text or ""

    if patterns["prohibition"].search(text):
        return "prohibition"
    if patterns["mandatory"].search(text):
        if current_type in {"recommendation", "conditional", ""}:
            return "mandatory"
        return current_type if current_type not in {"", "recommendation"} else "mandatory"
    if patterns["recommendation"].search(text) and not patterns["mandatory"].search(text):
        return "recommendation"
    return current_type or "mandatory"
