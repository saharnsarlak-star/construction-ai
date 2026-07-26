"""Extract analyzable text from CAD / BIM drawing files (DXF, DWG, Revit).

DXF: structured via ezdxf (TEXT, MTEXT, ATTRIB, layers, blocks).
DWG / Revit: no open full geometry reader in MVP — harvest printable
strings (ASCII + UTF-16LE) and keep construction-relevant tokens so
risk rules and topic coverage can use drawing content.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CAD_EXTENSIONS = {".dxf", ".dwg", ".rvt", ".rfa", ".rte", ".rft"}

_MAX_OUTPUT_CHARS = 120_000
_MAX_STRINGS = 4_000
_MIN_STRING_LEN = 3
_MAX_STRING_LEN = 200

# Drop pure noise from binary harvest.
_NOISE_RE = re.compile(
    r"^(?:"
    r"[0-9a-fA-F]{8,}"  # hex blobs
    r"|[A-Za-z]:\\.*"  # windows paths
    r"|\\\\.*"  # unc
    r"|https?://.*"
    r"|[\W_]+"  # punctuation-only
    r")$"
)

# Prefer strings that look like drawing/BIM content.
_KEEP_HINT = re.compile(
    r"("
    r"layer|block|wall|door|window|slab|beam|column|stair|roof|floor|level|"
    r"fire|hvac|elec|plumb|mech|struct|arch|civil|steel|concrete|rebar|"
    r"duct|pipe|cable|panel|room|grid|detail|section|plan|elevation|"
    r"نقشه|طبقه|دیوار|در|پنجره|ستون|تیر|سقف|پی|برق|مکانیک|حریق|اتاق|"
    r"wand|tür|decken|stütze|träger|brand|elektro|sanitär|ebene|"
    r"A[-_]?\d|S[-_]?\d|E[-_]?\d|M[-_]?\d|P[-_]?\d|"  # sheet codes
    r"DIN|ISO|NBR|NBC|ACI|VOB"
    r")",
    re.IGNORECASE,
)


def is_cad_file(path: Path) -> bool:
    return path.suffix.lower() in CAD_EXTENSIONS


def extract_cad_text(path: Path) -> str:
    """Return merged text suitable for tender risk analysis."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".dxf":
            text = _extract_dxf(path)
        elif suffix == ".dwg":
            text = _extract_dwg(path)
        elif suffix in {".rvt", ".rfa", ".rte", ".rft"}:
            text = _extract_revit(path)
        else:
            return f"[CAD_UNSUPPORTED] {path.name}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("CAD extract failed for %s", path.name)
        return f"[EXTRACT_ERROR] {path.name}: {exc}"

    text = (text or "").strip()
    if not text:
        return (
            f"[CAD_EMPTY] {path.name}\n"
            "No readable text/layers found in this CAD/BIM file."
        )
    if len(text) > _MAX_OUTPUT_CHARS:
        text = text[:_MAX_OUTPUT_CHARS] + "\n[CAD_TRUNCATED]"
    header = f"--- cad: {path.name} ({suffix.lstrip('.').upper()}) ---"
    return f"{header}\n{text}"


def _extract_dxf(path: Path) -> str:
    try:
        import ezdxf
        from ezdxf import recover
    except ImportError:
        return _harvest_binary(path, label="DXF-fallback")

    try:
        doc, auditor = recover.readfile(str(path))
    except Exception:
        try:
            doc = ezdxf.readfile(str(path))
            auditor = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("ezdxf failed on %s: %s — using string harvest", path.name, exc)
            return _harvest_binary(path, label="DXF-fallback")

    parts: list[str] = []
    try:
        layers = sorted({layer.dxf.name for layer in doc.layers})
        if layers:
            parts.append("Layers: " + ", ".join(layers[:500]))
    except Exception:  # noqa: BLE001
        pass

    texts: list[str] = []
    try:
        msp = doc.modelspace()
        for entity in msp:
            try:
                dtype = entity.dxftype()
                if dtype == "TEXT":
                    val = (entity.dxf.text or "").strip()
                    if val:
                        texts.append(val)
                elif dtype == "MTEXT":
                    val = (entity.text or getattr(entity.dxf, "text", "") or "").strip()
                    if val:
                        texts.append(val)
                elif dtype == "ATTRIB":
                    val = (entity.dxf.text or "").strip()
                    if val:
                        texts.append(val)
                elif dtype == "ATTDEF":
                    val = (entity.dxf.text or "").strip()
                    if val:
                        texts.append(val)
                elif dtype == "INSERT":
                    name = getattr(entity.dxf, "name", None)
                    if name:
                        texts.append(f"Block:{name}")
                    try:
                        for attrib in entity.attribs:
                            aval = (attrib.dxf.text or "").strip()
                            if aval:
                                texts.append(aval)
                    except Exception:  # noqa: BLE001
                        pass
                elif dtype.startswith("DIMENSION"):
                    ov = getattr(entity.dxf, "text", None) or ""
                    if ov and ov.strip() and ov.strip() != "<>":
                        texts.append(ov.strip())
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("DXF entity walk failed: %s", exc)

    # Block definitions (common for title blocks / symbols)
    try:
        for block in doc.blocks:
            if block.name.startswith("*"):
                continue
            texts.append(f"BlockDef:{block.name}")
    except Exception:  # noqa: BLE001
        pass

    unique_texts = _dedupe_keep_order(texts)[:_MAX_STRINGS]
    if unique_texts:
        parts.append("Texts:\n" + "\n".join(unique_texts))

    if auditor is not None:
        try:
            err_n = len(auditor.errors)
            if err_n:
                parts.append(f"[DXF_RECOVER] {err_n} recover notes")
        except Exception:  # noqa: BLE001
            pass

    if not parts:
        return _harvest_binary(path, label="DXF-fallback")
    return "\n".join(parts)


def _extract_dwg(path: Path) -> str:
    """DWG: try ODA converter if configured, else binary string harvest."""
    converted = _try_oda_to_dxf(path)
    if converted is not None:
        try:
            return _extract_dxf(converted)
        finally:
            try:
                converted.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
    return _harvest_binary(path, label="DWG")


def _extract_revit(path: Path) -> str:
    return _harvest_binary(path, label="Revit")


def _try_oda_to_dxf(path: Path) -> Path | None:
    """Optional: ezdxf ODA File Converter addon if installed on the host."""
    try:
        from ezdxf.addons import odafc
    except Exception:
        return None
    try:
        if not odafc.is_installed():
            return None
    except Exception:
        return None
    out = path.with_suffix(".dxf.tmp.dxf")
    try:
        odafc.convert(str(path), str(out), version="R2018", replace=True)
        if out.exists() and out.stat().st_size > 0:
            return out
    except Exception as exc:  # noqa: BLE001
        logger.info("ODA DWG→DXF unavailable/failed: %s", exc)
        try:
            out.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    return None


def _harvest_binary(path: Path, *, label: str) -> str:
    data = path.read_bytes()
    # Cap read for huge Revit models (still scan first + last chunks).
    max_scan = 40 * 1024 * 1024
    if len(data) > max_scan:
        half = max_scan // 2
        data = data[:half] + data[-half:]

    ascii_hits = re.findall(rb"[\x20-\x7E]{%d,%d}" % (_MIN_STRING_LEN, _MAX_STRING_LEN), data)
    utf16_hits = re.findall(
        (rb"(?:[\x20-\x7E]\x00){%d,%d}" % (_MIN_STRING_LEN, _MAX_STRING_LEN)),
        data,
    )

    strings: list[str] = []
    for raw in ascii_hits:
        try:
            s = raw.decode("ascii", errors="ignore").strip()
        except Exception:  # noqa: BLE001
            continue
        if _is_useful_string(s):
            strings.append(s)

    for raw in utf16_hits:
        try:
            s = raw.decode("utf-16le", errors="ignore").strip()
        except Exception:  # noqa: BLE001
            continue
        if _is_useful_string(s):
            strings.append(s)

    # Prefer hint-matching strings, then fill with other unique tokens.
    preferred = [s for s in strings if _KEEP_HINT.search(s)]
    other = [s for s in strings if not _KEEP_HINT.search(s)]
    merged = _dedupe_keep_order(preferred + other)[:_MAX_STRINGS]
    if not merged:
        return ""
    return f"[{label} strings]\n" + "\n".join(merged)


def _is_useful_string(s: str) -> bool:
    if not s or len(s) < _MIN_STRING_LEN or len(s) > _MAX_STRING_LEN:
        return False
    if _NOISE_RE.match(s):
        return False
    # Too many digits / low letter ratio → skip
    letters = sum(1 for c in s if c.isalpha())
    if letters < 2 and not _KEEP_HINT.search(s):
        return False
    # Skip long runs of same char
    if len(set(s)) <= 2 and len(s) > 6:
        return False
    return True


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
