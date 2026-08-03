"""Build Phase 8 test fixtures: drawing PDF + GAEB 90 D83 sample."""

from __future__ import annotations

from pathlib import Path


def _pad80(body: str, satznr: int) -> str:
    """Build an 80-char GAEB 90 line: content left, 6-digit Satznummer at cols 75-80."""
    nr = f"{satznr:06d}"
    core = body[:74].ljust(74)
    return core + nr


def write_gaeb90_d83(path: Path) -> Path:
    """Authentic GAEB 90 fixed-width sample (Freies GAEB Buch style, DA 83)."""
    rows = [
        _pad80("00 83L 12P00000090", 1),
        _pad80("01Musterdatei GAEB 90 DA 83 05.12.07 X", 2),
        _pad80("02MWM Muster aus MWM-Primo", 3),
        _pad80("03MWM", 4),
        _pad80("08EURO EURO", 5),
        _pad80("111 N", 6),
        _pad80("12L O S : 1", 7),
        _pad80("1110 N", 8),
        _pad80("12Abwasserleitung", 9),
        _pad80("21101 NNN 00000093000m", 10),
        _pad80("23101 00000125040 000001162873", 11),
        _pad80("25Entwaesserungsleitung aus Kunststoffrohren nach sta-", 12),
        _pad80("25tischen Erfordernissen nach DIN 4033 herstellen", 13),
        _pad80("25einschl. Erdarbeiten in Boden der Klassen 3 bis 5", 14),
        _pad80("26 sowie ggf. einschl. Verbau.", 15),
        _pad80("26 Ggf. erforderliche Wasserhaltung bis zu einer Pumpen-", 16),
        _pad80("21102 NNN 00000001000m", 17),
        _pad80("23102 00000134170 000000013417", 18),
        _pad80("25wie vor beschrieben, jedoch DN 125", 19),
        _pad80("21103 NNN 00000072000st", 20),
        _pad80("23103 00000071250 000000513000", 21),
        _pad80("25Zulage fuer Formstuecke zu entsprechender Entwaesse-", 22),
        _pad80("25rungsleitung", 23),
        _pad80("99", 24),
    ]
    for ln in rows:
        assert len(ln) == 80, f"bad len {len(ln)}: {ln!r}"
    path.write_text("\r\n".join(rows) + "\r\n", encoding="latin-1")
    return path


def write_drawing_pdf(path: Path) -> Path:
    """Minimal but real PDF sheet with title-block text triggering vision heuristics."""
    # Hand-authored PDF 1.4 with Helvetica text (no external deps)
    content_stream = b"""BT
/F1 14 Tf
50 780 Td
(ENGINEERING DRAWING - Sheet A-101) Tj
0 -24 Td
(Title: Hospital Wing Exterior Wall Wall-A) Tj
0 -20 Td
(Scale: 1:75) Tj
0 -20 Td
(Also marked SCALE 1:100 on section bubble) Tj
0 -24 Td
(PLAN VIEW - Level +3.20 FFL) Tj
0 -20 Td
(Wall-A length 12.50 m) Tj
0 -24 Td
(SECTION A-A - Level +2.80 FFL) Tj
0 -20 Td
(Plan conflicts with section: Wall-A height differs) Tj
0 -24 Td
(STEEL CONNECTION at grid B/3 - connection TBD) Tj
0 -20 Td
(Missing execution detail for critical junction) Tj
0 -24 Td
(Revision: B  Date: 2026-03-01) Tj
ET
"""
    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    stream = b"<< /Length %d >>\nstream\n" % len(content_stream) + content_stream + b"\nendstream\nendobj\n"
    objects.append(b"4 0 obj" + stream)
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    path.write_bytes(bytes(out))
    return path


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    write_gaeb90_d83(root / "sample_gaeb90.d83")
    write_drawing_pdf(root / "sample_drawing_sheet.pdf")
    print("Wrote", root / "sample_gaeb90.d83")
    print("Wrote", root / "sample_drawing_sheet.pdf")
