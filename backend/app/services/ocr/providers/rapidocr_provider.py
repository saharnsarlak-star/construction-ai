"""RapidOCR provider — secondary engine when Tesseract is missing/weak."""

from __future__ import annotations

import logging
import re

from app.services.ocr.base import BaseOCRService
from app.services.ocr.types import OcrPageResult

logger = logging.getLogger(__name__)


class RapidOCRService(BaseOCRService):
    def __init__(self) -> None:
        self._engine = None
        self._tried = False

    @property
    def name(self) -> str:
        return "rapidocr"

    def available(self) -> bool:
        if self._tried:
            return self._engine is not None
        self._tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        except Exception as exc:  # noqa: BLE001
            logger.warning("RapidOCR unavailable: %s", exc)
            self._engine = None
        return self._engine is not None

    def recognize_image(self, image, *, page_number: int = 1) -> OcrPageResult:
        if not self.available():
            return OcrPageResult(
                page=page_number,
                text="",
                confidence=0.0,
                needs_manual_review=True,
                source="ocr",
                kind="scanned",
                error="RapidOCR not available",
            )
        try:
            import numpy as np
            from PIL import Image

            if isinstance(image, Image.Image):
                arr = np.array(image.convert("RGB"))
            else:
                arr = image
            result, _ = self._engine(arr)
            lines: list[str] = []
            scores: list[float] = []
            if result:
                for row in result:
                    if len(row) > 1 and row[1]:
                        lines.append(str(row[1]))
                    if len(row) > 2:
                        try:
                            scores.append(float(row[2]) * 100.0)
                        except (TypeError, ValueError):
                            pass
            text = "\n".join(lines).strip()
            avg = sum(scores) / len(scores) if scores else (50.0 if text else 0.0)
            lang = "fa" if re.search(r"[\u0600-\u06FF]", text) else "en"
            return OcrPageResult(
                page=page_number,
                text=text,
                language=lang,
                confidence=avg,
                needs_manual_review=avg < 85.0 or len(text) < 20,
                source="ocr",
                kind="scanned",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("RapidOCR page %s failed: %s", page_number, exc)
            return OcrPageResult(
                page=page_number,
                text="",
                confidence=0.0,
                needs_manual_review=True,
                source="ocr",
                kind="scanned",
                error=str(exc),
            )
