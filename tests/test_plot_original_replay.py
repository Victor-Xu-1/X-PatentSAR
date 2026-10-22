"""A saved plot consensus cannot substitute for its actual original source."""

import copy
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.binding_original_replay import (
    original_binding_source_errors,
)
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from tests.test_plot_legend_rows import reference, two_row_plot


class PlotOriginalReplayTests(unittest.TestCase):
    def test_all_original_pixels_and_literal_rows_replay_without_ocr(self):
        with two_row_plot() as document:
            proof = reference(document, coarse=True)
            self.assertIsNotNone(proved_heading_declaration(proof))
            with patch(
                "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
                side_effect=AssertionError("Original replay cannot repeat OCR"),
            ):
                self.assertEqual(
                    original_binding_source_errors(
                        document, [], plot_references=(proof,)
                    ),
                    [],
                )
            # A changed non-target row must be detected, not just the selected ID.
            document[0].draw_line((350, 132), (370, 132), width=1)
            self.assertIsNotNone(proved_heading_declaration(proof))
            self.assertTrue(
                original_binding_source_errors(document, [], plot_references=(proof,))
            )

    def test_a_rehashed_internally_consistent_source_claim_is_not_the_original(self):
        with (
            two_row_plot() as original,
            two_row_plot(labels=("Compound 062-C", "Vehicle")) as other,
        ):
            old = reference(original, coarse=True)
            changed = reference(other, coarse=True)
            self.assertIsNotNone(proved_heading_declaration(old))
            self.assertIsNotNone(proved_heading_declaration(changed))
            self.assertTrue(
                original_binding_source_errors(original, [], plot_references=(changed,))
            )

    def test_removed_pixel_inventory_and_missing_original_page_refuse(self):
        with two_row_plot() as document:
            proof = reference(document, coarse=True)
            for mutation in ("page", "pixels", "literal", "axis"):
                with self.subTest(mutation=mutation):
                    changed = copy.deepcopy(proof)
                    if mutation == "page":
                        changed["page_no"] = 2
                    elif mutation == "pixels":
                        changed["original_locator"]["pixels"]["readings"] = []
                    elif mutation == "literal":
                        changed["original_locator"]["rows"][1]["cell"] = {}
                    else:
                        changed["figure_source"]["axis_refinement"][
                            "word_observations"
                        ] = {}
                    self.assertTrue(
                        original_binding_source_errors(
                            document, [], plot_references=(changed,)
                        )
                    )


if __name__ == "__main__":
    unittest.main()
