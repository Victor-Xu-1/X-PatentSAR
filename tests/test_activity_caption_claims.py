"""Caption location unification is not a scientific source-acceptance shortcut."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_caption_claims import (
    caption_nomination_bounds,
    same_caption_claim,
)
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_text_partition import line_owner
from patent_sar_extractor.core.activity_text_sources import text_source_owners
from tests.test_activity_parser_modules import draw_grid


class ActivityCaptionClaimTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page()
        draw_grid(
            self.page,
            [["No.", "IC50 (nM)"], ["31", "9"]],
            caption="Table 37. Binding activity",
        )
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError("Native source must not load OCR"),
        ):
            self.regions = extract_coordinate_tables(self.document, [0]).coverage
        tokens = self.regions[0]["layout"]["original_source"]["prefix"]["tokens"]
        self.box = [
            min(t["bbox"][0] for t in tokens),
            min(t["bbox"][1] for t in tokens),
            max(t["bbox"][2] for t in tokens),
            max(t["bbox"][3] for t in tokens),
        ]
        self.line = {
            "text": "Table37.Binding activity",
            "bbox": [
                self.box[0] + 0.5,
                self.box[1] + 0.5,
                self.box[2] - 0.5,
                self.box[3] - 0.5,
            ],
        }

    def test_only_marker_separators_not_literal_words_numbers_or_conditions_are_projected(
        self,
    ):
        for same in (
            "Table37.Binding activity",
            "Table 37: Binding activity",
            "Table 37 . Binding activity",
        ):
            self.assertTrue(same_caption_claim("Table 37. Binding activity", same))
        for different in (
            "Table 037. Binding activity",
            "Table 38. Binding activity",
            "Table 37. Bindingactivity",
            "Table 37. Binding activity 24 h",
            "Table 37. Binding Activity",
            "Some prose Table 37. Binding activity",
        ):
            self.assertFalse(
                same_caption_claim("Table 37. Binding activity", different)
            )

    def test_proposals_are_unified_before_reads_not_by_tolerating_a_post_read_clip(
        self,
    ):
        before = copy.deepcopy(self.line)
        self.assertIsNone(line_owner(self.line, self.regions))
        bounds = caption_nomination_bounds(
            self.line, self.regions, list(self.page.rect)[2:]
        )
        self.assertEqual(bounds, self.box)
        self.assertEqual(self.line, before)
        claim = line_owner({**self.line, "bbox": bounds}, self.regions)
        self.assertEqual(
            claim, {"role": "caption", "region_id": self.regions[0]["region_id"]}
        )
        # A nomination has no original current readings and cannot qualify itself.
        self.assertIsNone(
            text_source_owners(self.regions)({**self.line, "bbox": bounds})
        )

    def test_duplicate_physical_owners_never_choose_by_inventory_order(self):
        other = copy.deepcopy(self.regions[0])
        other["region_id"] = "f" * 32
        for regions in ([*self.regions, other], [other, *self.regions]):
            self.assertEqual(
                caption_nomination_bounds(self.line, regions, [595, 842]),
                self.line["bbox"],
            )
            complete = {**self.line, "bbox": self.box}
            self.assertEqual(line_owner(complete, regions)["role"], "ambiguous")

    def test_missing_or_changed_caption_words_do_not_expand_or_acquire_a_grid(self):
        for text in (
            "Table 37. Binding",
            "Table 37. Binding assay",
            "Table 38. Binding activity",
        ):
            line = {**self.line, "text": text}
            self.assertEqual(
                caption_nomination_bounds(line, self.regions, [595, 842]), line["bbox"]
            )
            self.assertIsNone(line_owner({**line, "bbox": self.box}, self.regions))

    def test_same_text_in_a_different_physical_row_is_not_a_caption_reference(self):
        line = {
            **self.line,
            "bbox": [self.box[0], self.box[1] + 250, self.box[2], self.box[3] + 250],
        }
        self.assertEqual(
            caption_nomination_bounds(line, self.regions, [595, 842]), line["bbox"]
        )
        self.assertIsNone(line_owner(line, self.regions))
