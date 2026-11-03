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
from patent_sar_extractor.core.activity_text_capture import capture_text_page
from patent_sar_extractor.core.activity_text_partition import line_owner
from patent_sar_extractor.core.activity_text_sources import text_source_owners
from tests.test_activity_parallel_grids import panel
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

    def parallel_caption(self):
        document = self.enterContext(fitz.open())
        page = document.new_page()
        self.parallel_page = page
        page.insert_text((40, 80), "Table 71. Target: JAK; Assay: binding", fontsize=9)
        headers = ["No.", "IC50 (nM)", "Dmax (%)"]
        panel(page, 40, 100, [headers, ["7", "3", "90"]])
        panel(page, 220, 100, [headers, ["9", "5", "80"]])
        regions = extract_coordinate_tables(document, [0]).coverage
        self.assertEqual(len(regions), 2)
        root = min(regions, key=lambda region: region["grid_axes"]["xs"][0])
        tokens = root["layout"]["original_source"]["prefix"]["tokens"]
        line = {
            "text": root["layout"]["context"]["raw_caption"],
            "bbox": [
                min(token["bbox"][0] for token in tokens),
                min(token["bbox"][1] for token in tokens),
                max(token["bbox"][2] for token in tokens),
                max(token["bbox"][3] for token in tokens),
            ],
        }
        return line, regions, root

    def test_shared_caption_resolves_only_to_its_proved_original_header_root(self):
        line, regions, root = self.parallel_caption()
        for ordered in (regions, list(reversed(regions))):
            self.assertEqual(
                line_owner(line, ordered),
                {"role": "caption", "region_id": root["region_id"]},
            )

    def test_a_duplicate_root_or_child_grid_does_not_become_a_shared_caption(self):
        line, regions, _root = self.parallel_caption()
        for original in regions:
            duplicate = copy.deepcopy(original)
            duplicate["region_id"] = "e" * 32
            for ordered in (
                [*regions, duplicate],
                [duplicate, *reversed(regions)],
            ):
                with self.subTest(original=original["region_id"]):
                    self.assertEqual(line_owner(line, ordered)["role"], "ambiguous")

    def test_changed_header_origin_does_not_reuse_a_cached_caption_family(self):
        _line, regions, root = self.parallel_caption()
        page = self.parallel_page
        source = capture_text_page(
            page, page.get_text("text"), coordinate_regions=regions
        )
        line = next(
            line
            for line in source["lines"]
            if same_caption_claim(
                line["text"], root["layout"]["context"]["raw_caption"]
            )
        )
        owner = text_source_owners(regions)
        self.assertEqual(
            owner(line), {"role": "caption", "region_id": root["region_id"]}
        )
        child = next(region for region in regions if region is not root)
        layout = child["layout"]
        xs, ys = layout["xs"], layout["ys"]
        layout["header_origin"] = {
            "page_no": child["page_no"],
            "bbox": [xs[0], ys[0], xs[-1], ys[layout["data_start"]]],
        }
        self.assertEqual(owner(line)["role"], "ambiguous")

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
