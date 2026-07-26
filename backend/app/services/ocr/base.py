"""Replaceable OCR provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from app.services.ocr.types import OcrPageResult


@runtime_checkable
class OCRService(Protocol):
    """Pluggable OCR engine — do not hard-code a vendor in the pipeline."""

    @property
    def name(self) -> str: ...

    def available(self) -> bool: ...

    def recognize_image(self, image, *, page_number: int = 1) -> OcrPageResult: ...


class BaseOCRService(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def recognize_image(self, image, *, page_number: int = 1) -> OcrPageResult: ...
