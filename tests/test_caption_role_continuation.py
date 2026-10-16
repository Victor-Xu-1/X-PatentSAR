"""Adjacent source catalogues keep title role, never infer IDs from sequences."""

import copy
import unittest

import fitz

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids


def two_pages(*, split=False, gap=False, new_title=None, shifted=False):
    doc = fitz.open()
    by_page, boxes, grids = {}, {}, {}
    pages = (1, 3) if gap else (1, 2)
    for number in range(1, pages[-1] + 1):
        page = doc.new_page()
        if number not in pages:
            continue
        position = pages.index(number)
        offset = 12 if shifted and position else 0
        xs = [x + offset for x in (50, 180, 310)]
        ys = (
            [100, 125, 205, 230]
            if split and not position
            else ([50, 130, 155, 235] if split else [100, 125, 205])
        )
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        if not position or new_title:
            page.insert_text(
                (xs[0], ys[0] - 15),
                new_title if position else "Table 47. Compounds",
                fontsize=10,
            )
        labels = ("41A", "89B") if not position else ("73C", "104D")
        label_row = 1 if split and position else 0
        by_page[number], boxes[number] = [], []
        for col, label in enumerate(labels):
            page.insert_text((xs[col] + 15, ys[label_row] + 17), label, fontsize=9)
            top = ys[label_row + 1] + 14
            box = (xs[col] + 20, top, xs[col] + 80, top + 35)
            by_page[number].append(
                {
                    "id": f"molecule-{number}-{col}",
                    "page_no": number,
                    **dict(zip(("x0", "y0", "x1", "y1"), box)),
                }
            )
            boxes[number].append(box)
            if split:
                if not position:
                    page.insert_text(
                        (xs[col] + 15, ys[-2] + 17), f"{col + 7}E", fontsize=9
                    )
                else:
                    earlier = (xs[col] + 20, 64, xs[col] + 80, 99)
                    by_page[number].append(
                        {
                            "id": f"split-{col}",
                            "page_no": number,
                            **dict(zip(("x0", "y0", "x1", "y1"), earlier)),
                        }
                    )
                    boxes[number].append(earlier)
        grids[number] = [{"xs": xs, "ys": ys}]
    return doc, by_page, boxes, grids, pages


def binding(pair):
    return {
        "cpd": f"Compound {pair['label']}",
        "structure_id": pair["structure"]["id"],
        "page_no": pair["structure"]["page_no"],
        **{
            f"struct_{axis}": pair["structure"][axis]
            for axis in ("x0", "y0", "x1", "y1")
        },
        "exact_caption_evidence": {
            "bbox": list(pair["label_bbox"]),
            "page_no": pair["label_page_no"],
            "observations": pair["observations"],
            "ownership": pair["ownership"],
        },
    }


class CaptionRoleContinuationTests(unittest.TestCase):
    def observe(self, **options):
        doc, structures, boxes, grids, pages = two_pages(**options)
        with doc:
            return bind_caption_grids(
                doc,
                structures,
                boxes,
                pages,
                grids_for_page=lambda page: grids.get(page.number + 1, []),
            )

    def test_adjacent_same_geometry_carries_role_without_number_sequence(self):
        result = self.observe()
        self.assertEqual(
            [b["label"] for b in result.bindings], ["41A", "89B", "73C", "104D"]
        )
        self.assertEqual(result.issues, [])
        for pair in result.bindings:
            self.assertTrue(valid_caption_binding_evidence(binding(pair)))

    def test_caption_and_its_structure_can_cross_one_proved_page_boundary(self):
        result = self.observe(split=True)
        self.assertEqual(
            {b["label"] for b in result.bindings},
            {"41A", "89B", "7E", "8E", "73C", "104D"},
        )
        self.assertEqual(result.issues, [])
        for pair in result.bindings:
            self.assertTrue(valid_caption_binding_evidence(binding(pair)))

    def test_page_gap_changed_columns_or_new_unknown_catalogue_stops_inheritance(self):
        for options in (
            {"gap": True},
            {"shifted": True},
            {"new_title": "Table 48. Structures"},
        ):
            with self.subTest(options=options):
                result = self.observe(**options)
                self.assertEqual([b["label"] for b in result.bindings], ["41A", "89B"])
                self.assertTrue(result.issues)

    def test_removed_previous_role_cannot_promote_saved_continuation(self):
        result = self.observe()
        pair = result.bindings[-1]
        item = binding(pair)
        self.assertTrue(valid_caption_binding_evidence(item))
        changed = copy.deepcopy(item)
        del changed["exact_caption_evidence"]["ownership"]["caption_role"][
            "continuation"
        ]
        self.assertFalse(valid_caption_binding_evidence(changed))

    def test_matching_explicit_continued_title_retains_the_same_original_role(self):
        result = self.observe(new_title="Table 47. Continued")
        self.assertEqual(
            [b["label"] for b in result.bindings], ["41A", "89B", "73C", "104D"]
        )
        self.assertEqual(result.issues, [])

    def test_current_nonfinal_or_same_number_different_role_does_not_borrow_a_final_role(
        self,
    ):
        for title in (
            "Table 47. Intermediates",
            "Table 47. Structures",
            "Table 48. Continued",
        ):
            with self.subTest(title=title):
                result = self.observe(new_title=title)
                self.assertEqual([b["label"] for b in result.bindings], ["41A", "89B"])

    def test_saved_continuation_rechecks_both_axes_page_and_bounded_ancestry(self):
        pair = self.observe().bindings[-1]
        original = binding(pair)
        for field, value in (
            ("previous_axes", {"xs": [0, 130, 260], "ys": [100, 125, 205]}),
            ("current_axes", {"xs": [50, 181, 310], "ys": [100, 125, 205]}),
            ("direction", "nearest"),
        ):
            changed = copy.deepcopy(original)
            changed["exact_caption_evidence"]["ownership"]["caption_role"][
                "continuation"
            ][field] = value
            with self.subTest(field=field):
                self.assertFalse(valid_caption_binding_evidence(changed))
        circular = copy.deepcopy(original)
        role = circular["exact_caption_evidence"]["ownership"]["caption_role"]
        role["continuation"]["previous"] = role
        self.assertFalse(valid_caption_binding_evidence(circular))
