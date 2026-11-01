"""Original caption layout is not conditional on complete detector recall."""

import unittest

import fitz

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import (
    bind_caption_grids,
    caption_frame_index,
)
from patent_sar_extractor.core.unruled_structure_observation import (
    observe_unruled_tables,
)
from tests.test_caption_role_continuation import binding


def original_grid(*, missing_drawing=False, unread_caption=False):
    """Native text and vector ink; no private PDF or recognizer predictions."""
    document = fitz.open()
    page = document.new_page()
    xs, ys = [50, 180, 310], [100, 125, 205]
    page.insert_text((50, 85), "Table 47. Structures", fontsize=10)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    structures, boxes = [], []
    for column, label in enumerate(("41A", "89B")):
        text = "Compound ?" if unread_caption and column == 1 else "Compound " + label
        page.insert_text((xs[column] + 12, 117), text, fontsize=8)
        box = [xs[column] + 20, 145, xs[column] + 80, 180]
        page.draw_polyline(
            [(box[0], 170), ((box[0] + box[2]) / 2, 145), (box[2], 170)]
        )
        if not (missing_drawing and column == 1):
            structures.append(
                {
                    "id": f"generated-{column}",
                    "page_no": 1,
                    **dict(zip(("x0", "y0", "x1", "y1"), box, strict=True)),
                }
            )
            boxes.append(box)
    return document, {1: structures}, {1: boxes}, [{"xs": xs, "ys": ys}]


def observations(**options):
    document, structures, boxes, grids = original_grid(**options)
    with document:
        captions = bind_caption_grids(
            document,
            structures,
            boxes,
            [1],
            grids_for_page=lambda _page: grids,
        )
        columns = observe_unruled_tables(
            document,
            structures[1],
            [0],
            lambda _page: grids,
            lambda _page: captions.tokens[1],
            page_texts=[document[0].get_text()],
            caption_roles=captions.roles,
            caption_frames=caption_frame_index(captions.bindings),
        )
        return captions, columns


class CaptionFrameInventoryTests(unittest.TestCase):
    def assert_original_pairs(self, captions, expected):
        self.assertEqual(len(captions.bindings), expected, captions.issues)
        self.assertTrue(
            all(
                valid_caption_binding_evidence(binding(pair))
                for pair in captions.bindings
            )
        )

    def test_complete_prefixed_caption_inventory_keeps_its_original_layout(self):
        captions, columns = observations()
        self.assert_original_pairs(captions, 2)
        self.assertEqual(captions.issues, [])
        self.assertEqual(columns[1], [])

    def test_missing_candidate_keeps_caption_failure_without_competing_columns(self):
        captions, columns = observations(missing_drawing=True)
        self.assert_original_pairs(captions, 1)
        self.assertIn(
            "missing_caption_structure", [item["reason"] for item in captions.issues]
        )
        self.assertEqual(
            columns[1],
            [],
            "Complete original prefixed caption cells retain their layout even "
            "when a drawing candidate is missing; the missing association must "
            "stay failed in that same caption inventory",
        )

    def test_unread_original_caption_cannot_supply_complete_layout_permission(self):
        captions, columns = observations(unread_caption=True)
        self.assert_original_pairs(captions, 1)
        self.assertIn(
            "unread_or_conflicting_caption",
            [item["reason"] for item in captions.issues],
        )
        self.assertTrue(columns[1], "Unproved source cells must not disappear")


if __name__ == "__main__":
    unittest.main()
