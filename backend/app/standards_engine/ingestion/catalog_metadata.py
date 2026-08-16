"""Parse catalog-standard file headers — country-agnostic metadata extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class CatalogFileMetadata:
    standard_code: str | None = None
    country_code: str | None = None
    title_fa: str | None = None
    title_en: str | None = None
    publisher: str | None = None
    standard_version: str | None = None
    effective_date: date | None = None
    volume: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "standard_code": self.standard_code,
            "country_code": self.country_code,
            "title_fa": self.title_fa,
            "title_en": self.title_en,
            "publisher": self.publisher,
            "standard_version": self.standard_version,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "volume": self.volume,
        }


_HEADER_RE = re.compile(r"^([A-Z_]+):\s*(.+)$")

# Jalali yyyy/mm/dd in catalog sample files (Iran standards)
_JALALI_DATE_RE = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")

# Persian headers in Word-extracted Standard 55 (no KEY: value block)
_LAST_EDIT_RE = re.compile(
    r"آخرین\s*ویرایش\s*[:：]?\s*(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
    re.UNICODE,
)
_JALALI_INLINE_RE = re.compile(r"\b(1[34]\d{2})[/-](\d{1,2})[/-](\d{1,2})\b")
_VOLUME_RE = re.compile(r"جلد\s*(اول|دوم|سوم|\d+)", re.UNICODE)
_PUBLISHER_HINT_RE = re.compile(r"سازمان\s+برنامه", re.UNICODE)


def _parse_effective_date(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    # ISO
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    # Jalali stored as opaque version string when conversion unavailable
    m = _JALALI_DATE_RE.match(text)
    if m:
        # Keep as synthetic ISO placeholder only when year looks Gregorian; else store in version
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            try:
                return date(y, int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _parse_header_block_metadata(text: str) -> CatalogFileMetadata:
    """Read KEY: value headers from dev sample files."""
    meta = CatalogFileMetadata()
    for line in (text or "").replace("\r\n", "\n").splitlines()[:30]:
        if line.strip().startswith("---CLAUSE"):
            break
        m = _HEADER_RE.match(line.strip())
        if not m:
            continue
        key, val = m.group(1).strip().upper(), m.group(2).strip()
        if key == "STANDARD":
            meta.title_fa = val
        elif key == "COUNTRY":
            meta.country_code = val.upper()[:8] if val else None
        elif key == "PUBLISHER":
            meta.publisher = val
        elif key == "VOLUME":
            meta.volume = val
        elif key == "EFFECTIVE_DATE":
            meta.effective_date = _parse_effective_date(val)
            if meta.effective_date is None and val:
                meta.standard_version = meta.standard_version or f"effective_{val.replace('/', '-')}"
        elif key == "STANDARD_VERSION":
            meta.standard_version = val
        elif key == "STANDARD_CODE":
            meta.standard_code = val
    if meta.volume and not meta.standard_version:
        meta.standard_version = meta.volume
    return meta


def _parse_jalali_version(date_str: str) -> tuple[date | None, str | None]:
    """Parse Jalali yyyy/mm/dd; return ISO date only when year looks Gregorian."""
    m = _JALALI_DATE_RE.match(date_str.strip())
    if not m:
        return None, None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if 1300 <= y <= 1500:
        return None, f"effective_{y}-{mo:02d}-{d:02d}"
    if 1900 <= y <= 2100:
        try:
            return date(y, mo, d), None
        except ValueError:
            return None, None
    return None, None


def parse_word_body_metadata(text: str) -> CatalogFileMetadata:
    """Extract metadata from Persian Word/PDF body text (e.g. Standard 55 cover pages)."""
    meta = CatalogFileMetadata()
    sample = (text or "").replace("\r\n", "\n")[:12_000]

    if _PUBLISHER_HINT_RE.search(sample):
        meta.publisher = "سازمان برنامه و بودجه کشور"

    vol = _VOLUME_RE.search(sample)
    if vol:
        meta.volume = f"جلد {vol.group(1)}"

    edit = _LAST_EDIT_RE.search(sample)
    if edit:
        date_str = edit.group(1).strip()
        eff, ver = _parse_jalali_version(date_str)
        if eff:
            meta.effective_date = eff
        elif ver:
            meta.standard_version = ver

    if not meta.standard_version and not meta.effective_date:
        inline = _JALALI_INLINE_RE.search(sample)
        if inline:
            date_str = f"{inline.group(1)}/{inline.group(2)}/{inline.group(3)}"
            eff, ver = _parse_jalali_version(date_str)
            if eff:
                meta.effective_date = eff
            elif ver:
                meta.standard_version = ver

    if "ضابطه" in sample and re.search(r"\b55\b|۱-۵۵|1-55", sample):
        meta.title_fa = (
            "ضابطه شماره ۵۵ - مشخصات فنی عمومی کارهای ساختمانی (بازنگری سوم)"
        )

    if re.search(r"[\u0600-\u06FF]", sample):
        meta.country_code = "IR"

    if meta.volume and not meta.standard_version:
        meta.standard_version = meta.volume
    return meta


def _merge_metadata(primary: CatalogFileMetadata, secondary: CatalogFileMetadata) -> CatalogFileMetadata:
    """Fill empty fields in primary from secondary."""
    for field in (
        "standard_code",
        "country_code",
        "title_fa",
        "title_en",
        "publisher",
        "standard_version",
        "effective_date",
        "volume",
    ):
        if getattr(primary, field) is None and getattr(secondary, field) is not None:
            setattr(primary, field, getattr(secondary, field))
    return primary


def parse_catalog_file_metadata(text: str) -> CatalogFileMetadata:
    """Read metadata from sample headers and/or Persian Word body text."""
    header_meta = _parse_header_block_metadata(text)
    if header_meta.country_code or header_meta.title_fa or header_meta.publisher:
        return header_meta
    return _merge_metadata(header_meta, parse_word_body_metadata(text))


def merge_catalog_metadata(
    asset_fields: dict[str, Any],
    file_meta: CatalogFileMetadata,
    *,
    default_country: str | None = None,
) -> dict[str, Any]:
    """Fill missing catalog asset fields from file metadata (does not overwrite non-empty)."""
    out = dict(asset_fields)
    if file_meta.country_code and not out.get("country_code"):
        out["country_code"] = file_meta.country_code
    elif default_country and not out.get("country_code"):
        out["country_code"] = default_country
    if file_meta.standard_version and not out.get("standard_version"):
        out["standard_version"] = file_meta.standard_version
    if file_meta.effective_date and not out.get("effective_date"):
        out["effective_date"] = file_meta.effective_date
    if file_meta.publisher and not out.get("publisher"):
        out["publisher"] = file_meta.publisher
    if file_meta.title_fa and not out.get("title_fa"):
        out["title_fa"] = file_meta.title_fa
    return out
