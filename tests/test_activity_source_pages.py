"""Discovered grid pages keep their own text inventory even when parsing refuses."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_auxiliary_replay import original_pdf_reader
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_text_sources import required_text_page_keys
from patent_sar_extractor.core.page_ocr_cache import page_text
from tests.test_activity_parser_modules import draw_grid


class ActivitySourcePageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError("Native page inventory must not start OCR"),
            )
        )
        self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.runtime.AuxiliaryTextRuntime",
                side_effect=AssertionError("No auxiliary model is allowed"),
            )
        )

    def capture(self, *, independent_text=False, empty_grid=False):
        pdf = self.root / "two-page-original.pdf"
        with fitz.open() as document:
            draw_grid(
                document.new_page(),
                [["No.", "IC50 (nM)"], ["31", "9"]],
                caption="Table A. Target: JAK; Assay: binding",
            )
            page = document.new_page()
            rows = [["No.", "Unspecified result"]]
            if not empty_grid:
                rows.append(["44", "0.3"])
            draw_grid(page, rows, caption="Table B. Unspecified observations")
            if independent_text:
                page.insert_text(
                    (60, 300),
                    "Table C. Target: BET; Assay: binding\nNo. | DC50 (nM)\n57 | 0.8",
                    fontsize=9,
                )
            document.save(pdf)
        # Exercise the physical continuation/discovery path independently of
        # whether the text nominator happens to recognize an unrelated caption.
        reads = []

        def read_original(page, **options):
            reads.append(page.number)
            return page_text(page, **options)

        with (
            patch(
                "patent_sar_extractor.core.activity_extractor.discover_activity_sources",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_extractor.page_text",
                side_effect=read_original,
            ),
        ):
            result = extract(str(pdf), {"activity_pages": [0]}, str(self.root / "out"))
        self.assertEqual(reads, [0, 1], "Each required native page is read only once")
        return pdf, result, load_json(self.root / "out/activity_data.json", {})

    def test_page_requirements_do_not_depend_on_parse_success_or_mix_index_bases(self):
        self.assertEqual(
            required_text_page_keys(
                {
                    "seed_pages": [1, 1],
                    "discovered_pages": [6],
                    "regions": [
                        {"page_no": 3, "kind": "grid", "status": "unresolved"},
                        {"page_no": 9, "kind": "grid", "status": "non_activity"},
                        {"page_no": 42, "kind": "text", "status": "unresolved"},
                    ],
                }
            ),
            {"2", "3", "7", "9"},
        )

    def test_unowned_discovered_grid_page_keeps_complete_native_text_source(self):
        for empty in (False, True):
            with self.subTest(empty_grid=empty):
                pdf, _result, data = self.capture(empty_grid=empty)
                coverage = data["coverage"]
                self.assertTrue(
                    any(
                        region["page_no"] == 2 and region["kind"] == "grid"
                        for region in coverage["regions"]
                    )
                )
                self.assertEqual(set(coverage["text_pages"]), {"1", "2"})
                self.assertEqual(set(coverage["text_sources"]), {"1", "2"})
                with fitz.open(pdf) as document:
                    self.assertEqual(
                        coverage["text_sources"]["2"]["nomination_text"],
                        document[1].get_text("text").rstrip(),
                    )
                errors = activity_evidence_errors(
                    data, [0], open_original=original_pdf_reader(pdf)
                )
                self.assertFalse(
                    any(
                        "lack their complete coordinate/text partition inventory"
                        in error
                        for error in errors
                    )
                )
                self.assertTrue(
                    errors, "An unsupported/empty grid must not become accepted"
                )

    def test_independent_result_on_discovered_unowned_page_is_not_silently_lost(self):
        pdf, result, data = self.capture(independent_text=True)
        self.assertIn("Compound 57", {row.cpd for row in result["rows"]})
        self.assertNotIn("Compound 44", {row.cpd for row in result["rows"]})
        self.assertTrue(
            any(
                region["page_no"] == 2
                and region["kind"] == "grid"
                and region["status"] == "unresolved"
                for region in data["coverage"]["regions"]
            )
        )
        self.assertTrue(
            activity_evidence_errors(data, [0], open_original=original_pdf_reader(pdf))
        )


if __name__ == "__main__":
    unittest.main()
