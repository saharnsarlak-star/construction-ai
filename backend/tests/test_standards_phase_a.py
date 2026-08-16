"""Unit tests for Standards Engine clause parsing (Phase A)."""

from __future__ import annotations

import unittest

from app.standards_engine.ingestion.clause_parser import parse_standards_text
from app.standards_engine.ingestion.pdf_extract import PageText, build_merged_text_from_pages
from app.standards_engine.ingestion.requirement_validate import validate_requirements


class ClauseParserTests(unittest.TestCase):
    def test_sample_markers_parse_five_clauses(self) -> None:
        sample = """
---CLAUSE 2-2-3-1---
شماره بند: 2-2-3-1
عنوان: راهرو
متن:
راهرو باید حداقل 2.5 متر ارتفاع داشته باشد.

---CLAUSE 2-2-3-2---
شماره بند: 2-2-3-2
عنوان: سقف
متن:
سقف موقت باید مقاوم باشد.
"""
        clauses = parse_standards_text(sample, mode="sample")
        self.assertEqual(len(clauses), 2)
        self.assertEqual(clauses[0]["clause_number"], "2-2-3-1")

    def test_numbered_clauses_with_page_map(self) -> None:
        pages = [
            PageText(page=10, text="2-2-3-1 - راهرو\nمتن بند اول"),
            PageText(page=11, text="2-2-3-2 - سقف\nمتن بند دوم"),
        ]
        merged = build_merged_text_from_pages(pages)
        clauses = parse_standards_text(merged, mode="numbered")
        self.assertGreaterEqual(len(clauses), 2)
        nums = {c["clause_number"] for c in clauses}
        self.assertIn("2-2-3-1", nums)
        self.assertIn("2-2-3-2", nums)
        by_num = {c["clause_number"]: c for c in clauses}
        self.assertEqual(by_num["2-2-3-1"].get("source_page"), 10)

    def test_section_prefix_filter(self) -> None:
        text = "2-2-3-1 - a\nbody\n3-1-1 - b\nbody2"
        clauses = parse_standards_text(text, mode="numbered", section_prefix="2-2")
        self.assertTrue(all(str(c["clause_number"]).startswith("2-2") for c in clauses))


    def test_toc_stub_filtered(self) -> None:
        text = (
            "2-2-3-1 - عنوان .................... 12\n"
            "2-2-3-2 - راهرو\n"
            "راهرو باید حداقل 2.5 متر ارتفاع داشته باشد و عرض کافی داشته باشد.\n"
        )
        clauses = parse_standards_text(text, mode="numbered")
        nums = {c["clause_number"] for c in clauses}
        self.assertNotIn("2-2-3-1", nums)
        self.assertIn("2-2-3-2", nums)

    def test_virtual_source_page_for_word_text(self) -> None:
        text = "2-2-3-1 - راهرو\n" + ("متن بند با محتوای کافی برای استخراج.\n" * 5)
        clauses = parse_standards_text(text, mode="numbered")
        self.assertEqual(len(clauses), 1)
        self.assertIsNotNone(clauses[0].get("source_page"))

    def test_word_body_metadata_persian(self) -> None:
        from app.standards_engine.ingestion.catalog_metadata import parse_catalog_file_metadata

        header = (
            "ضابطه شماره 1-55 مشخصات فنی عمومی\n"
            "آخرین ویرایش: 1404/04/01\n"
            "جلد اول\n"
            "سازمان برنامه و بودجه کشور\n"
        )
        meta = parse_catalog_file_metadata(header)
        self.assertEqual(meta.country_code, "IR")
        self.assertIn("جلد", meta.volume or "")
        self.assertEqual(meta.publisher, "سازمان برنامه و بودجه کشور")


class RequirementValidateTests(unittest.TestCase):
    def test_modality_correction_bayad(self) -> None:
        raw = [
            {
                "requirement_type": "recommendation",
                "requirement_text": "راهرو باید حداقل 2.5 متر ارتفاع داشته باشد.",
            }
        ]
        out, warnings = validate_requirements(raw, clause_number="2-2-3-1")
        self.assertEqual(out[0]["requirement_type"], "mandatory")
        self.assertTrue(any(w["code"] == "modality_corrected" for w in warnings))

    def test_thickness_width_split(self) -> None:
        raw = [
            {
                "requirement_type": "mandatory",
                "requirement_text": "از الوارهایی با ضخامت 5 و عرض 25 سانتیمتر استفاده شود.",
            }
        ]
        out, warnings = validate_requirements(raw, clause_number="2-2-3-2")
        self.assertEqual(len(out), 2)
        self.assertTrue(any(w["code"] == "thickness_width_split" for w in warnings))


    def test_english_shall_modality(self) -> None:
        raw = [{"requirement_type": "recommendation", "requirement_text": "Walkways shall be minimum 2.5 m high."}]
        out, warnings = validate_requirements(raw, clause_number="1.2.3", locale="en")
        self.assertEqual(out[0]["requirement_type"], "mandatory")
        self.assertTrue(any(w["code"] == "modality_corrected" for w in warnings))

    def test_catalog_metadata_from_sample_header(self) -> None:
        from app.standards_engine.ingestion.catalog_metadata import parse_catalog_file_metadata

        header = "COUNTRY: DE\nSTANDARD_VERSION: din_18065\nEFFECTIVE_DATE: 2024-01-15\n"
        meta = parse_catalog_file_metadata(header)
        self.assertEqual(meta.country_code, "DE")
        self.assertEqual(meta.standard_version, "din_18065")
        self.assertEqual(str(meta.effective_date), "2024-01-15")


if __name__ == "__main__":
    unittest.main()
