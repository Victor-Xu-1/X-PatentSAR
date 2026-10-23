"""Exact original measurement forms survive extraction into existing SAR rules."""

import copy
import tempfile
import unittest
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_auxiliary_replay import original_pdf_reader
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.activity_identity import is_value, value_tokens
from patent_sar_extractor.core.activity_join import (
    activity_evidence_errors,
    activity_order_and_map,
)
from patent_sar_extractor.core.activity_text_rows import parse_segment
from patent_sar_extractor.core.cell_frame_proof import original_cell_frame_matches
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.measurements import parse_measurement
from patent_sar_extractor.core.sar.values import compare_values, parse_value
from patent_sar_extractor.core.source_cell_claims import cell_source_conflict
from patent_sar_extractor.core.table_cells import activity_kind_matches
from patent_sar_extractor.web.artifacts import _activities
from tests import test_activity_parser_modules as grid_fixture


class ActivityMeasurementLiteralTests(unittest.TestCase):
    def test_activity_producer_serializes_complete_original_range_and_replays_its_pdf(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "generated.pdf"
            with fitz.open() as doc:
                grid_fixture.draw_grid(
                    doc.new_page(),
                    [
                        ["No.", "IC50 (nM)", "Dmax (%)"],
                        ["042B", "[1,10)", "80"],
                        ["7A", ".05", "92"],
                    ],
                )
                doc.save(pdf)
            before = pdf.read_bytes()
            produced = extract(
                str(pdf), {"activity_pages": [0]}, str(root / "activity")
            )
            saved = load_json(root / "activity/activity_data.json", {})
            self.assertEqual(saved["rows"][0]["activity_values"]["IC50 (nM)"], "[1,10)")
            self.assertEqual(len(produced["rows"]), 2)
            self.assertEqual(
                activity_evidence_errors(
                    saved, [0], open_original=original_pdf_reader(pdf)
                ),
                [],
            )
            self.assertEqual(pdf.read_bytes(), before)
            with fitz.open(pdf) as changed:
                changed[0].insert_text((215, 140), "X", fontsize=8)
                changed.saveIncr()
            self.assertTrue(
                activity_evidence_errors(
                    saved, [0], open_original=original_pdf_reader(pdf)
                )
            )

    def test_scalar_cell_uses_the_same_grammar_without_new_models_or_source_changes(
        self,
    ):
        for literal in ("[1,10)", ".05", "2..8", "<=.5"):
            with self.subTest(literal=literal), fitz.open() as draft:
                source = draft.new_page(width=200, height=100)
                source.insert_text((30, 50), literal, fontsize=10)
                doc = self.enterContext(
                    fitz.open(stream=draft.tobytes(), filetype="pdf")
                )
                page = doc[0]
                bounds = [20, 30, 180, 65]
                tokens = [
                    {"text": literal, "x": 60, "y": 45, "bbox": [30, 40, 105, 53]}
                ]
                before = doc.tobytes(no_new_id=True)

                def reader(image, *, use_det, use_cls, literal=literal):
                    return [[literal, 0.999]], None

                with patch(
                    "patent_sar_extractor.core.table_cells.get_ocr_engine",
                    return_value=("rapidocr", reader),
                ):
                    value, observations, review = read_activity_cell(
                        page,
                        tokens,
                        bounds,
                        identifier=False,
                        native=False,
                        kind="number",
                    )
                self.assertEqual(value, literal)
                self.assertFalse(review)
                captured = next(
                    o for o in observations if o["method"] == "cell_ocr_400dpi"
                )
                self.assertTrue(original_cell_frame_matches(captured, page))
                self.assertEqual(doc.tobytes(no_new_id=True), before)
                page.insert_text((120, 55), "x", fontsize=7)
                self.assertFalse(original_cell_frame_matches(captured, page))

    def test_numeric_kind_does_not_admit_grades_and_legacy_uncertainty_is_not_a_scalar(
        self,
    ):
        for raw in ("[1,10)", ".05", "1 ± 0.2", "1,25"):
            self.assertTrue(activity_kind_matches(raw, "number"))
        for raw in ("A", "++", "[1,10)"):
            self.assertFalse(
                activity_kind_matches(raw, "letter")
                if raw.startswith("[")
                else activity_kind_matches(raw, "number")
            )
        for raw in ("1 ± 0.2", "1,25"):
            with self.assertRaises(SARInputError):
                parse_value(raw, {})

    def test_unpositioned_missing_and_extra_values_remain_withheld_not_shifted(self):
        for tail in ("[1,10)", "[1,10) 80 90"):
            rows = parse_segment(
                "Table 19. Binding", "No. IC50 (nM) Dmax (%)\n042B " + tail, page_no=1
            )
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0].needs_review)
            self.assertTrue(
                all(not value for value in rows[0].activity_values.values())
            )
            self.assertIn(tail, str(rows[0].activity_sources))

    def test_exact_numeric_forms_already_supported_by_sar_are_extraction_values(self):
        for literal in (
            ".05",
            "1.",
            "[1,10)",
            "(1,10]",
            "[-2,-.5]",
            "2..8",
            "1–10",
            "1e-3-2e-3",
            "<=.5",
            ">=.5",
            "1E+3",
            "[1,1]",
        ):
            with self.subTest(literal=literal):
                self.assertIn(parse_value(literal, {}).kind, {"scalar", "interval"})
                self.assertTrue(is_value(literal))

    def test_explicit_units_do_not_erase_interval_boundaries(self):
        for literal, expected in (
            ("[.001,.01) µM", (Decimal(1), Decimal(10), True, False)),
            ("2..8 nM", (Decimal(2), Decimal(8), True, True)),
            (">=.05 nM", (Decimal(".05"), Decimal("Infinity"), True, False)),
        ):
            with self.subTest(literal=literal):
                self.assertTrue(is_value(literal))
                parsed = parse_measurement(literal, {}, "nM")
                self.assertEqual(
                    (parsed.low, parsed.high, parsed.lower_closed, parsed.upper_closed),
                    expected,
                )

    def test_text_lexer_preserves_complete_intervals_without_shifting_columns(self):
        for raw, expected in (
            ("[1,10) 80", ["[1,10)", "80"]),
            ("( .1 , 2.5 ] 3..9", ["( .1 , 2.5 ]", "3..9"]),
            ("1e-3-2e-3 .05", ["1e-3-2e-3", ".05"]),
            ("[1,10) nM 80%", ["[1,10) nM", "80%"]),
            ("1 ± 0.2 80", ["1 ± 0.2", "80"]),
            ("1,25 80", ["1,25", "80"]),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(value_tokens(raw), expected)

    def test_malformed_reversed_nonfinite_or_overbudget_forms_are_not_values(self):
        for literal in (
            "[10,1]",
            "(1,1]",
            "[1,2",
            "1..",
            "1-2-3",
            "NaN",
            "1e309",
            "[1e-400,2]",
            "1/2",
            "x .05",
            "[1,2] inventedUnit",
            "1" * 257,
        ):
            with self.subTest(literal=literal):
                self.assertFalse(is_value(literal))
                self.assertIsNone(value_tokens(literal))

    def test_declared_text_table_retains_interval_and_other_endpoint_as_separate_cells(
        self,
    ):
        rows = parse_segment(
            "Table 19. Assay: binding",
            "No. IC50 (nM) Dmax (%)\n042B [1,10) 80\n7A .05 92",
            page_no=1,
        )
        self.assertEqual([row.cpd for row in rows], ["Compound 042B", "Compound 7A"])
        self.assertEqual(
            rows[0].activity_values, {"IC50 (nM)": "[1,10)", "Dmax (%)": "80"}
        )
        self.assertEqual(rows[1].activity_values["IC50 (nM)"], ".05")
        self.assertFalse(any(row.needs_review for row in rows))

    def test_native_grid_join_and_web_keep_originals_not_midpoints(self):
        with fitz.open() as doc:
            grid_fixture.draw_grid(
                doc.new_page(),
                [
                    ["No.", "IC50 (nM)", "Dmax (%)"],
                    ["042B", "[1,10)", "80"],
                    ["7A", ".05", "92"],
                ],
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(len(result.rows), 2)
        self.assertFalse(any(row.needs_review for row in result.rows))
        rows = [asdict(row) for row in result.rows]
        before = copy.deepcopy(rows)
        order, joined = activity_order_and_map(rows)
        self.assertEqual(order, ["Compound 042B", "Compound 7A"])
        self.assertEqual(joined["Compound 042B"]["IC50 (nM)"], "[1,10)")
        displayed = [a.value for row in rows for a in _activities(row, page_count=1)]
        self.assertIn("[1,10)", displayed)
        self.assertIn(".05", displayed)
        self.assertEqual(rows, before)

    def test_original_claim_cannot_be_replaced_by_an_interval_midpoint_or_changed_endpoint(
        self,
    ):
        observed = {"method": "native_cell", "text": "[1,10)"}
        self.assertFalse(cell_source_conflict(observed, "[1,10)", "number"))
        for changed in ("5.5", "[1,10]", "[2,10)", "1", "<10"):
            self.assertTrue(cell_source_conflict(observed, changed, "number"))

    def test_interval_order_and_error_codes_remain_the_existing_sar_policy(self):
        self.assertEqual(
            compare_values(
                parse_value(">=10", {}), parse_value("[1,10)", {}), "lower", {}
            )[0],
            "better",
        )
        self.assertEqual(
            compare_values(
                parse_value("[5,20]", {}), parse_value("[1,10)", {}), "lower", {}
            )[0],
            "indeterminate",
        )
        for raw, expected in (
            ("[2,1]", "invalid_interval"),
            ("1e309", "numeric_limit_exceeded"),
            ("bad 1", "unsupported_measurement_value"),
        ):
            with self.subTest(raw=raw), self.assertRaises(SARInputError) as error:
                parse_value(raw, {})
            self.assertEqual(error.exception.code, expected)
