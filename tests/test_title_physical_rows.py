"""The same physical row authority owns raster catalogue-title recovery."""

import copy
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.source_observations import source_cell_observation
from patent_sar_extractor.core.source_paint_visibility import native_paint_view
from patent_sar_extractor.core.title_original_replay import replay_source_title
from patent_sar_extractor.core.title_source_capture import observe_source_title
from patent_sar_extractor.core.title_source_proof import source_title_text
from tests.test_heading_physical_rows import controlled_reader, raster_heading


def token(text, bounds):
    return {
        "text": text,
        "bbox": list(bounds),
        "x": (bounds[0] + bounds[2]) / 2,
        "y": (bounds[1] + bounds[3]) / 2,
        "source": "raster",
        "geometry_space": "rendered",
        "confidence": 0.99,
    }


def nominated_title(page, heading, *, same_row_boundary=False):
    layout = source_layout(page)
    words = [
        token(heading["text"], heading["bbox"]),
        token("Previous result", [40, 76, 192, 84]),
    ]
    bounds = [0, 82, page.rect.width, 95]
    if same_row_boundary:
        words[-1] = token("Intermediate", [10, 85, 47, 93])
        bounds[0] = 40
    return source_cell_observation(
        SourceTokens(words, layout, layout.raster_bounds), bounds
    )


class TitlePhysicalRowTests(unittest.TestCase):
    def observe(self, page, raw, text):
        with (
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                return_value=("rapidocr", controlled_reader(text)),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            ),
        ):
            return observe_source_title(
                page,
                raw,
                layout=source_layout(page),
                paint_view=native_paint_view(page),
            )

    def test_adjacent_boundary_locator_does_not_veto_the_independent_complete_title(
        self,
    ):
        literal = "Table 47. Examples of Compounds"
        with raster_heading(literal) as (_, page, heading):
            raw = nominated_title(page, heading)
            self.assertTrue(raw["boundary_tokens"])
            proof = self.observe(page, raw, literal)
            self.assertEqual(source_title_text(proof), literal)
            self.assertEqual(proof["nomination_source"], raw)
            self.assertTrue(proof["nomination_source"]["boundary_tokens"])
            replay_source_title(page, proof)

    def test_known_table_identity_cannot_be_outvoted_after_boundary_recovery(self):
        with raster_heading("Table 47. Examples of Compounds") as (_, page, heading):
            proof = self.observe(
                page, nominated_title(page, heading), "Table 48. Examples of Compounds"
            )
            self.assertIsNone(source_title_text(proof))

    def test_a_boundary_claim_on_the_selected_row_is_not_discarded(self):
        literal = "Table 47. Examples of Compounds"
        with raster_heading(literal) as (_, page, heading):
            proof = self.observe(
                page, nominated_title(page, heading, same_row_boundary=True), literal
            )
            self.assertIsNone(source_title_text(proof))

    def test_known_nonfinal_role_cannot_be_outvoted_after_boundary_recovery(self):
        with raster_heading("Table 47. Intermediate Compounds") as (_, page, heading):
            proof = self.observe(
                page, nominated_title(page, heading), "Table 47. Examples of Compounds"
            )
            self.assertIsNone(source_title_text(proof))

    def test_an_inset_or_forged_pixel_recipe_does_not_prove_boundary_ownership(self):
        literal = "Table 47. Examples of Compounds"
        with raster_heading(literal) as (_, page, heading):
            proof = self.observe(page, nominated_title(page, heading), literal)
            self.assertEqual(source_title_text(proof), literal)
            changed = copy.deepcopy(proof)
            changed["title_scope"]["pixels"]["readings"][0]["source_window"][
                "purpose"
            ] = "text"
            self.assertIsNone(source_title_text(changed))

    def test_removing_row_ownership_does_not_turn_a_boundary_claim_into_a_title(self):
        literal = "Table 47. Examples of Compounds"
        with raster_heading(literal) as (_, page, heading):
            proof = self.observe(page, nominated_title(page, heading), literal)
            self.assertEqual(source_title_text(proof), literal)
            changed = copy.deepcopy(proof)
            changed["title_scope"] = None
            self.assertIsNone(source_title_text(changed))


if __name__ == "__main__":
    unittest.main()
