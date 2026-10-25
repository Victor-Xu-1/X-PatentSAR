"""Generated native originals exercise caption ownership, not OCR accuracy."""

import copy
import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core import page_ocr_cache
from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import coverage_errors
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.text_ocr import configuration
from patent_sar_extractor.web.artifacts import _activities
from tests.test_activity_context_windows import draw_grid, parallel_activity_page


def caption_document(*, continued=False, current_prefix="[ 42 ]", prior_rows=True):
    document = fitz.open()
    page = document.new_page(width=500, height=600)
    if continued:
        page.insert_text(
            (40, 40),
            "[ 41 ] Table 9. Cellular activity\nTarget: MET\nDuration: 24 h",
            fontsize=9,
        )
    else:
        page.insert_text(
            (40, 40), "Table 8. Target: ABL; Assay: binding\nDuration: 2 h", fontsize=9
        )
        if prior_rows:
            draw_grid(page, 70, [["No.", "IC50 (nM)"], ["99C", "4.7"]])
        page.insert_text(
            (40, 150),
            f"{current_prefix} Table 9. Cellular activity\nCell line: U2OS\nDuration: 24 h",
            fontsize=9,
        )
    draw_grid(page, 220, [["No.", "IC50 (nM)"], ["17B", "2.3"]])
    if continued:
        page = document.new_page(width=500, height=600)
        page.insert_text(
            (40, 40),
            f"{current_prefix} Table 9. Cellular activity (continued)\nDuration: 24 h",
            fontsize=9,
        )
        draw_grid(page, 120, [["99C", "4.7"]])
    return document


class CaptionLocatorNativeTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(page_ocr_cache, "_OCR_ENGINE", None))
        self.primary = self.enterContext(
            patch.object(
                page_ocr_cache,
                "_build_ocr_engine",
                side_effect=AssertionError("No OCR is permitted"),
            )
        )
        self.auxiliary = self.enterContext(
            patch.object(
                configuration,
                "get_auxiliary_text_runtime",
                side_effect=AssertionError("No auxiliary OCR is permitted"),
            )
        )

    def tearDown(self):
        self.primary.assert_not_called()
        self.auxiliary.assert_not_called()

    def payload(self, parsed, document):
        # Coordinate rows alone are not a complete saved-source artifact.
        # Exercise the production facade's real text inventory/partition too;
        # keep every original context assertion and deliberate source mutation.
        with tempfile.TemporaryDirectory(prefix="native-caption-source-") as root:
            root = Path(root)
            original = root / "original.pdf"
            document.save(original)
            output = root / "output"
            full = extract(str(original), {"activity_pages": [0]}, str(output))
            self.assertEqual(full["rows"], parsed.rows)
            return load_json(output / "activity_data.json", {})

    def test_native_source_and_saved_consumers_do_not_borrow_old_conditions(self):
        with caption_document() as document:
            parsed = extract_coordinate_tables(document, [0])
            self.assertEqual(
                [row.cpd for row in parsed.rows], ["Compound 99C", "Compound 17B"]
            )
            prior, row = parsed.rows
            self.assertEqual(prior.activity_sources[0]["table_id"], "Table 8")
            self.assertEqual(prior.activity_sources[0]["target"], "ABL")
            self.assertEqual(prior.activity_sources[0]["assay"], "binding")
            self.assertEqual(prior.activity_sources[0]["duration"], "2 h")
            self.assertFalse(row.needs_review)
            source = row.activity_sources[0]
            self.assertEqual(source["table_id"], "Table 9")
            self.assertIsNone(source["target"])
            self.assertIsNone(source["assay"])
            self.assertEqual(source["cell_line"], "U2OS")
            self.assertEqual(source["duration"], "24 h")
            self.assertIn("[ 42 ] Table 9", source["raw_caption"])
            payload = self.payload(parsed, document)
            self.assertEqual(
                coverage_errors(payload["coverage"], [0], rows=payload["rows"]), []
            )
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                [],
            )
            projected = _activities(asdict(row), page_count=1)
            self.assertEqual(len(projected), 1)
            self.assertEqual(projected[0].source_table, "Table 9")
            altered = copy.deepcopy(payload)
            altered["rows"][1]["activity_sources"][0]["target"] = "ABL"
            self.assertTrue(
                coverage_errors(altered["coverage"], [0], rows=altered["rows"])
            )
            for record in altered["coverage"]["regions"]:
                if (
                    record.get("layout", {}).get("context", {}).get("table_id")
                    == "Table 9"
                ):
                    record["layout"]["context"]["target"] = "ABL"
            self.assertTrue(
                original_activity_source_errors(
                    altered, open_original=lambda: nullcontext(document)
                )
            )

    def test_a_declared_result_table_without_rows_remains_unresolved(self):
        with caption_document(prior_rows=False) as document:
            parsed = extract_coordinate_tables(document, [0])
            self.assertEqual([row.cpd for row in parsed.rows], ["Compound 17B"])
            payload = self.payload(parsed, document)
            self.assertTrue(
                any(
                    "no_original_rows" in error
                    for error in coverage_errors(
                        payload["coverage"], [0], rows=payload["rows"]
                    )
                )
            )
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                [],
            )
            self.assertTrue(
                activity_evidence_errors(
                    payload, [0], open_original=lambda: nullcontext(document)
                )
            )

    def test_explicit_continuation_keeps_its_original_source_and_condition_gate(self):
        with caption_document(continued=True) as document:
            parsed = extract_coordinate_tables(document, [0])
            self.assertEqual(
                [row.cpd for row in parsed.rows], ["Compound 17B", "Compound 99C"]
            )
            self.assertTrue(all(not row.needs_review for row in parsed.rows))
            source = parsed.rows[-1].activity_sources[0]
            self.assertEqual(source["table_id"], "Table 9")
            self.assertEqual(source["target"], "MET")
            self.assertEqual(source["duration"], "24 h")
            self.assertEqual(source["header_region"]["page_no"], 1)
            payload = self.payload(parsed, document)
            self.assertEqual(
                coverage_errors(payload["coverage"], [0], rows=payload["rows"]), []
            )
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                [],
            )
            document[1].draw_rect(
                fitz.Rect(35, 35, 390, 76), color=None, fill=(1, 1, 1)
            )
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                )
            )

    def test_missing_or_downgraded_current_boundary_cannot_borrow_a_parent_header(self):
        with caption_document(continued=True) as document:
            parsed = extract_coordinate_tables(document, [0])
            payload = self.payload(parsed, document)
            for downgrade in (False, True):
                altered = copy.deepcopy(payload)
                layout = next(
                    r["layout"]
                    for r in altered["coverage"]["regions"]
                    if r.get("layout", {}).get("data_start") == 0
                )
                if downgrade:
                    layout["continuation_context"]["version"] = 1
                    layout["continuation_context"].pop("original_pixels")
                else:
                    layout.pop("continuation_context")
                with self.subTest(downgrade=downgrade):
                    self.assertTrue(
                        original_activity_source_errors(
                            altered, open_original=lambda: nullcontext(document)
                        )
                    )

    def test_fullwidth_native_locator_keeps_verbatim_caption_and_same_original_gate(
        self,
    ):
        with fitz.open() as document:
            page = document.new_page(width=500, height=400)
            page.insert_text(
                (40, 40),
                "［００４２］ Table 9. Cellular activity",
                fontname="china-s",
                fontsize=9,
            )
            page.insert_text((40, 65), "Assay: binding\nDuration: 24 h", fontsize=9)
            draw_grid(page, 120, [["No.", "IC50 (nM)"], ["17B", "2.3"]])
            parsed = extract_coordinate_tables(document, [0])
            self.assertEqual([row.cpd for row in parsed.rows], ["Compound 17B"])
            self.assertFalse(parsed.rows[0].needs_review)
            source = parsed.rows[0].activity_sources[0]
            self.assertIn("［００４２］", source["raw_caption"])
            self.assertEqual(source["table_id"], "Table 9")
            self.assertEqual(source["assay"], "binding")
            payload = self.payload(parsed, document)
            self.assertEqual(
                coverage_errors(payload["coverage"], [0], rows=payload["rows"]), []
            )
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                [],
            )

    def test_hidden_parallel_panel_condition_cannot_borrow_a_visible_parent(self):
        with fitz.open() as document:
            parallel_activity_page(document, panel_assays=("enzyme", "cell", "binding"))
            parsed = extract_coordinate_tables(document, [0])
            self.assertTrue(parsed.rows)
            self.assertTrue(all(not row.needs_review for row in parsed.rows))
            payload = self.payload(parsed, document)
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                [],
            )
            document[0].draw_rect(
                fitz.Rect(269, 138, 439, 154), color=None, fill=(1, 1, 1)
            )
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                )
            )


if __name__ == "__main__":
    unittest.main()
