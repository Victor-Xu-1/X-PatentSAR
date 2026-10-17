"""Original-word partition boundaries without rendering or invented table rules."""

import unittest

from patent_sar_extractor.core.logical_column_partitions import (
    caption_logical_band,
    header_partitions,
    nominate_unruled_headers,
)


def word(text, box):
    return {
        "text": text,
        "bbox": box,
        "x": (box[0] + box[2]) / 2,
        "y": (box[1] + box[3]) / 2,
    }


class LogicalColumnPartitionTests(unittest.TestCase):
    def setUp(self):
        self.groups = [
            {"text": "Compound No.", "bbox": [45, 70, 100, 80]},
            {"text": "Structure", "bbox": [150, 70, 190, 80]},
            {"text": "Compound No.", "bbox": [365, 70, 420, 80]},
            {"text": "Structure", "bbox": [470, 70, 510, 80]},
        ]
        self.captions = [
            {"text": "Table 11. Compounds", "bbox": [40, 33, 130, 45]},
            {"text": "Table B8. Intermediates", "bbox": [360, 18, 470, 30]},
        ]
        self.size = [660, 720]

    def partitions(self, groups=None, captions=None):
        return header_partitions(
            groups or self.groups,
            captions if captions is not None else self.captions,
            self.size,
            66,
        )

    def test_distinct_literal_positions_do_not_require_equal_title_baselines(self):
        nominated = self.partitions()
        self.assertEqual([n["selection"] for n in nominated], [[0, 2], [2, 4]])
        self.assertEqual([n["band"] for n in nominated], [[0, 360], [360, 660]])
        self.assertTrue(all(n["groups"] is self.groups for n in nominated))
        self.assertEqual(
            caption_logical_band(self.captions[1], self.captions, nominated, self.size),
            [360, 660],
        )

    def test_one_global_title_cannot_be_expanded_into_two_independent_sources(self):
        nominated = self.partitions(captions=self.captions[:1])
        self.assertEqual([n["selection"] for n in nominated], [[0, 4]])
        self.assertEqual(nominated[0]["band"], [0, 660])

    def test_overlapping_caption_positions_do_not_authorize_column_splitting(self):
        captions = [self.captions[0] | {"bbox": [40, 33, 390, 45]}, self.captions[1]]
        self.assertEqual(len(self.partitions(captions=captions)), 1)

    def test_a_complete_header_crossing_a_proposed_band_is_not_cut_or_dropped(self):
        groups = [
            self.groups[0],
            self.groups[1] | {"bbox": [330, 70, 385, 80]},
            *self.groups[2:],
        ]
        self.assertEqual(self.partitions(groups=groups)[0]["selection"], [0, 4])

    def test_a_title_start_cannot_split_an_original_identifier_header(self):
        captions = [self.captions[0], self.captions[1] | {"bbox": [390, 18, 500, 30]}]
        self.assertEqual(self.partitions(captions=captions)[0]["selection"], [0, 4])

    def test_original_metadata_groups_stay_inside_the_selected_header_inventory(self):
        groups = [
            *self.groups[:2],
            {"text": "MW", "bbox": [275, 70, 292, 80]},
            *self.groups[2:],
        ]
        nominated = self.partitions(groups=groups)
        self.assertEqual([n["selection"] for n in nominated], [[0, 3], [3, 5]])
        self.assertEqual(len(nominated[0]["groups"]), 5)

    def test_bounded_nomination_uses_the_same_literal_header_and_caption_parts(self):
        tokens = [word(g["text"], g["bbox"]) for g in self.groups + self.captions]
        self.assertEqual(nominate_unruled_headers(tokens, self.size), self.partitions())

    def test_a_caption_outside_the_complete_context_budget_cannot_divide_the_row(self):
        groups = [
            g | {"bbox": [g["bbox"][0], 500, g["bbox"][2], 510]} for g in self.groups
        ]
        nominated = header_partitions(groups, self.captions, self.size, 496)
        self.assertEqual(nominated[0]["selection"], [0, 4])

    def test_source_disagreement_is_not_resolved_by_voting_on_a_caption_field(self):
        conflicting = self.captions + [
            self.captions[1] | {"text": "Table B8. Compounds"}
        ]
        self.assertEqual(self.partitions(captions=conflicting), self.partitions())
        # The partition is geometry only; raw claims are never rewritten.
        self.assertEqual(conflicting[-1]["text"], "Table B8. Compounds")
        self.assertEqual(conflicting[1]["text"], "Table B8. Intermediates")

    def test_source_inventory_overflow_is_explicit_not_silent_truncation(self):
        with self.assertRaises(ValueError):
            self.partitions(captions=[self.captions[0]] * 4097)


if __name__ == "__main__":
    unittest.main()
