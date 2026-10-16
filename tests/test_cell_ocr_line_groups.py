"""Physical-row grouping is shared, bounded, and independent of identifier text."""

import unittest

from patent_sar_extractor.core.cell_ocr_line_groups import group_text_lines


def box(left, top, right, bottom):
    return {"bbox": [[left, top], [right, top], [right, bottom], [left, bottom]]}


class CellOCRLineGroupTests(unittest.TestCase):
    def test_jittered_nonoverlapping_words_stay_in_one_physical_row(self):
        parts = [box(80, 2, 100, 20), box(30, 6, 50, 22), box(0, 1, 20, 21)]
        groups = group_text_lines(parts)
        self.assertEqual(len(groups), 1)
        self.assertCountEqual(groups[0], parts)

    def test_tall_box_bridging_two_rows_has_no_unique_owner(self):
        self.assertIsNone(
            group_text_lines(
                [
                    box(0, 0, 20, 10),
                    box(0, 20, 20, 30),
                    box(30, 0, 50, 30),
                ]
            )
        )

    def test_pairwise_membership_prevents_transitive_row_merging(self):
        self.assertIsNone(
            group_text_lines(
                [
                    box(0, 0, 20, 20),
                    box(30, 8, 50, 28),
                    box(60, 16, 80, 36),
                ]
            )
        )

    def test_row_and_detection_limits_are_not_silently_truncated(self):
        self.assertIsNone(
            group_text_lines([box(i * 10, 0, i * 10 + 8, 20) for i in range(33)])
        )
        self.assertIsNone(
            group_text_lines([box(0, i * 30, 20, i * 30 + 20) for i in range(9)])
        )
        self.assertEqual(
            len(group_text_lines([box(0, i * 30, 20, i * 30 + 20) for i in range(8)])),
            8,
        )

    def test_empty_detector_inventory_remains_empty(self):
        self.assertEqual(group_text_lines([]), [])
