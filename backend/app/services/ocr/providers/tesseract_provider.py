"""Tesseract OCR provider — Persian + German + English."""

from __future__ import annotations

import logging
import re

from app.services.ocr.base import BaseOCRService
from app.services.ocr.types import OcrPageResult

logger = logging.getLogger(__name__)

# Prefer multilingual packs when installed; degrade gracefully.
_LANG_CANDIDATES = (
    "fas+deu+eng",
    "fas+eng",
    "deu+eng",
    "eng",
)

_TABLE_HINTS = re.compile(
    r"(\|[^\n]+\||\t.+\t|ردیف|مقدار|واحد|Item\s*No|Qty|Einheit)",
    re.IGNORECASE,
)
_STAMP_HINTS = re.compile(r"(مهر|امضا|stamp|sealed|Siegel|Unterschrift)", re.IGNORECASE)
_SIGNATURE_HINTS = re.compile(r"(امضا|signature|gezeichnet|signed\s+by)", re.IGNORECASE)
_DRAWING_HINTS = re.compile(
    r"(elevation|plan|section|grid|A-\d|S-\d|تراز|محور|اتاق|Room\s*\d|EL\.\s*\+|Ø|㎜|mm\b)",
    re.IGNORECASE,
)


class TesseractOCRService(BaseOCRService):
    def __init__(self) -> None:
        self._ok: bool | None = None
        self._lang: str = "eng"

    @property
    def name(self) -> str:
        return f"tesseract:{self._lang}"

    def available(self) -> bool:
        if self._ok is not None:
            return self._ok
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            self._lang = self._pick_lang()
            self._ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tesseract unavailable: %s", exc)
            self._ok = False
        return self._ok

    def _pick_lang(self) -> str:
        import pytesseract

        try:
            installed = set(pytesseract.get_languages(config=""))
        except Exception:  # noqa: BLE001
            installed = {"eng"}
        for candidate in _LANG_CANDIDATES:
            parts = candidate.split("+")
            if all(p in installed for p in parts):
                return candidate
        return "eng" if "eng" in installed else next(iter(installed), "eng")

    def recognize_image(self, image, *, page_number: int = 1) -> OcrPageResult:
        if not self.available():
            return OcrPageResult(
                page=page_number,
                text="",
                confidence=0.0,
                needs_manual_review=True,
                source="ocr",
                kind="scanned",
                error="Tesseract not available",
            )
        try:
            import pytesseract
            from PIL import Image

            if not isinstance(image, Image.Image):
                image = Image.open(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")

            # OSD can fix rotated pages; ignore failures.
            try:
                osd = pytesseract.image_to_osd(image)
                rot = re.search(r"Rotate:\s*(\d+)", osd or "")
                if rot:
                    angle = int(rot.group(1))
                    if angle and angle % 360 != 0:
                        image = image.rotate(360 - angle, expand=True)
            except Exception:  # noqa: BLE001
                pass

            data = pytesseract.image_to_data(
                image, lang=self._lang, output_type=pytesseract.Output.DICT
            )
            words: list[str] = []
            confs: list[float] = []
            for txt, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
                token = (txt or "").strip()
                try:
                    c = float(conf)
                except (TypeError, ValueError):
                    c = -1.0
                if token and c >= 0:
                    words.append(token)
                    confs.append(c)
            text = " ".join(words).strip()
            if not text:
                text = (pytesseract.image_to_string(image, lang=self._lang) or "").strip()
            avg = sum(confs) / len(confs) if confs else (40.0 if text else 0.0)
            language = self._detect_lang(text)
            return OcrPageResult(
                page=page_number,
                text=text,
                language=language,
                confidence=avg,
                contains_tables=bool(_TABLE_HINTS.search(text)),
                contains_drawing=bool(_DRAWING_HINTS.search(text)),
                contains_stamp=bool(_STAMP_HINTS.search(text)),
                contains_signature=bool(_SIGNATURE_HINTS.search(text)),
                needs_manual_review=avg < 85.0 or len(text) < 20,
                source="ocr",
                kind="scanned",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tesseract page %s failed: %s", page_number, exc)
            return OcrPageResult(
                page=page_number,
                text="",
                confidence=0.0,
                needs_manual_review=True,
                source="ocr",
                kind="scanned",
                error=str(exc),
            )

    @staticmethod
    def _detect_lang(text: str) -> str:
        if re.search(r"[\u0600-\u06FF]", text):
            return "fa"
        if re.search(r"[äöüÄÖÜß]", text):
            return "de"
        return "en"
