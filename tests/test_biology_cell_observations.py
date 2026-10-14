"""Printed biology values retain original whole-cell proof and contradictions."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.activity_result_references import _observed
from patent_sar_extractor.core.cell_cross_observation import printed_cross_valid
from patent_sar_extractor.core.cell_ocr_observation import OCRObservation
from patent_sar_extractor.core.table_cells import _normalize

BOUNDS = (70, 95, 170, 125)


def observed_crosses(count=3, text=None):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text(
            (90, 115), text if text is not None else "+" * count, fontsize=12
        )
        value, sources, review = read_activity_cell(
            page,
            [{"text": "+", "x": 100, "y": 110}],
            BOUNDS,
            identifier=False,
            native=False,
            kind="plus",
        )
    return {"value": value, "observations": sources, "bbox": list(BOUNDS)}, review


class BiologyCellObservationTests(unittest.TestCase):
    def test_original_cross_count_qualifies_whole_cell_not_page_locator_count(self):
        for count in (1, 2, 3):
            cell, review = observed_crosses(count)
            self.assertEqual(cell["value"], "+" * count)
            self.assertFalse(review)
            self.assertTrue(_observed(cell))
            proof = cell["observations"][-1]
            self.assertTrue(printed_cross_valid(proof, BOUNDS, cell["value"]))
            self.assertEqual(proof["readings"][0]["threshold"], 150)
            self.assertEqual(proof["readings"][1]["threshold"], 200)

    def test_valid_native_conflict_cannot_be_erased_by_saved_components(self):
        cell, _ = observed_crosses(3)
        cell["observations"].append({"method": "native_cell", "text": "+"})
        self.assertFalse(_observed(cell))
        cell["observations"][-1] = {"method": "page_ocr_cell", "text": "2"}
        self.assertFalse(_observed(cell))

    def test_forged_component_text_shape_threshold_or_geometry_is_refused(self):
        original, _ = observed_crosses(3)
        for field, value in (
            ("text", "+"),
            ("bbox", [0, 0, 100, 30]),
            ("dpi", 450.0),
            ("image_sha256", "foreign"),
            ("image_size", [0, 0]),
            ("readings", [{"threshold": True, "components": []}]),
        ):
            cell = copy.deepcopy(original)
            cell["observations"][-1][field] = value
            with self.subTest(field=field):
                self.assertFalse(_observed(cell))
        cell = copy.deepcopy(original)
        cell["observations"][-1]["readings"][0]["components"][0][4] = 99999
        self.assertFalse(_observed(cell))
        cell = copy.deepcopy(original)
        cell["observations"][-1]["readings"][1]["components"][0][0] += 100
        self.assertFalse(_observed(cell))

    def test_letter_noise_and_excess_crosses_cannot_claim_printed_count(self):
        for text in ("X", "A", "t", "T", "*", "+X", "++++"):
            with self.subTest(text=text):
                cell, review = observed_crosses(text=text)
                self.assertTrue(review)
                self.assertFalse(_observed(cell))

    def test_scanned_original_grades_and_missing_readings_keep_one_lexical_policy(self):
        for value, kind in (
            ("G", "letter"),
            ("F2", "letter"),
            ("ND", "number"),
            ("N/A", "number"),
        ):
            with self.subTest(value=value), fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((90, 115), value, fontsize=12)
                reading = OCRObservation(value, 0.99, value)
                with patch(
                    "patent_sar_extractor.core.table_cells._ocr_cell",
                    return_value=reading,
                ):
                    result, sources, review = read_activity_cell(
                        page,
                        [{"text": value, "x": 100, "y": 110}],
                        BOUNDS,
                        identifier=False,
                        native=False,
                        kind=kind,
                    )
                self.assertEqual(result, value)
                self.assertFalse(review)
                self.assertTrue(
                    _observed(
                        {"value": result, "observations": sources, "bbox": list(BOUNDS)}
                    )
                )
        self.assertEqual(_normalize("G", "letter"), "G")
        self.assertEqual(_normalize("H", "letter"), "")
        self.assertEqual(_normalize("ND", "id"), "")
