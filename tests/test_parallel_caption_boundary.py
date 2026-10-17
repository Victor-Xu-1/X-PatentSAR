"""Independent original catalogue columns must not overwrite page-boundary state."""

import copy
import unittest

import fitz

from patent_sar_extractor.core.activity_context_geometry import MAX_TABLES
from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from tests.test_caption_page_boundary import below_pages
from tests.test_caption_role_continuation import binding, two_pages


def parallel_catalogues(*, left_options=None, right_options=None, above=False):
    if above:
        left, left_structures, _boxes, left_grids, _pages = two_pages(split=True)
        right, right_structures, _boxes, right_grids, _pages = two_pages(split=True)
        for rows in right_structures.values():
            for row in rows:
                row["id"] = "right-" + row["id"]
    else:
        left, left_structures, _boxes, left_grids = below_pages(**(left_options or {}))
        right, right_structures, _boxes, right_grids = below_pages(
            label_prefix="9", table_number=99, **(right_options or {})
        )
    combined = fitz.open()
    structures, boxes, grids = {}, {}, {}
    with left, right:
        for number in (1, 2):
            width, height = left[number - 1].rect.width, left[number - 1].rect.height
            page = combined.new_page(width=2 * width, height=height)
            structures[number], boxes[number], grids[number] = [], [], []
            for source, observed, frames, offset in (
                (left, left_structures, left_grids, 0),
                (right, right_structures, right_grids, width),
            ):
                page.show_pdf_page(
                    fitz.Rect(offset, 0, offset + width, height), source, number - 1
                )
                grids[number].extend(
                    {"xs": [x + offset for x in grid["xs"]], "ys": grid["ys"]}
                    for grid in frames[number]
                )
                for row in observed[number]:
                    item = {**row, "x0": row["x0"] + offset, "x1": row["x1"] + offset}
                    structures[number].append(item)
                    boxes[number].append(
                        tuple(item[key] for key in ("x0", "y0", "x1", "y1"))
                    )
    return combined, structures, boxes, grids


class ParallelCaptionBoundaryTests(unittest.TestCase):
    def test_over_limit_frame_inventory_refuses_before_token_or_cell_reads(self):
        doc, structures, boxes, grids = below_pages()
        with doc, self.assertRaisesRegex(ValueError, "frame resource bound"):
            bind_caption_grids(
                doc,
                structures,
                boxes,
                [1],
                grids_for_page=lambda page: grids[1] * (MAX_TABLES + 1),
                tokens_for_page=lambda page: self.fail("Overflow must not start OCR"),
            )

    def test_parallel_catalogues_keep_each_original_owner_across_the_same_page_break(
        self,
    ):
        doc, structures, boxes, grids = parallel_catalogues()
        with doc:
            result = bind_caption_grids(
                doc,
                structures,
                boxes,
                [1, 2],
                grids_for_page=lambda page: grids[page.number + 1],
            )
        self.assertEqual(result.issues, [])
        self.assertEqual(len(result.bindings), 12)
        for pair in result.bindings:
            self.assertEqual(pair["structure"]["id"], f"original-{pair['label']}")
            self.assertTrue(valid_caption_binding_evidence(binding(pair)))

    def test_parallel_pending_captions_keep_both_next_page_drawing_owners(self):
        doc, structures, boxes, grids = parallel_catalogues(above=True)
        with doc:
            result = bind_caption_grids(
                doc,
                structures,
                boxes,
                [1, 2],
                grids_for_page=lambda page: grids[page.number + 1],
            )
        self.assertEqual(result.issues, [])
        self.assertEqual(
            {(p["label"], p["structure"]["id"]) for p in result.bindings},
            {
                (label, prefix + identity)
                for prefix in ("", "right-")
                for label, identity in (
                    ("41A", "molecule-1-0"),
                    ("89B", "molecule-1-1"),
                    ("7E", "split-0"),
                    ("8E", "split-1"),
                    ("73C", "molecule-2-0"),
                    ("104D", "molecule-2-1"),
                )
            },
        )
        self.assertTrue(
            all(valid_caption_binding_evidence(binding(p)) for p in result.bindings)
        )

    def test_one_columns_new_context_or_shift_does_not_erase_the_other_column(self):
        for options, right_options in (
            (
                {"next_title": "Table 48. Intermediates"},
                {"next_title": "Table 99. Continued"},
            ),
            ({"tail_text": "Table 48. Intermediates"}, {}),
            ({"shift": 12}, {}),
        ):
            with self.subTest(options=options):
                doc, structures, boxes, grids = parallel_catalogues(
                    left_options=options, right_options=right_options
                )
                with doc:
                    result = bind_caption_grids(
                        doc,
                        structures,
                        boxes,
                        [1, 2],
                        grids_for_page=lambda page, frames=grids: frames[
                            page.number + 1
                        ],
                    )
                right = [p for p in result.bindings if p["structure"]["x0"] >= 380]
                self.assertEqual(len(right), 6)
                self.assertTrue(
                    all(valid_caption_binding_evidence(binding(p)) for p in right)
                )
                self.assertFalse(
                    any(p["label"] in {"7E", "8E"} for p in result.bindings)
                )
                self.assertTrue(result.issues)

    def test_earlier_same_column_table_cannot_compete_with_the_true_boundary_frame(
        self,
    ):
        doc, structures, boxes, grids = below_pages()
        with doc:
            page, xs, ys = doc[0], [50, 180, 310], [20, 50, 70]
            page.insert_text((50, 10), "Table 46. Compounds", fontsize=8)
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            for column, label in enumerate(("3Z", "15K")):
                page.insert_text((xs[column] + 15, 65), f"Compound {label}", fontsize=8)
                box = (xs[column] + 20, 30, xs[column] + 80, 42)
                structures[1].append(
                    {
                        "id": f"original-{label}",
                        "page_no": 1,
                        **dict(zip(("x0", "y0", "x1", "y1"), box)),
                    }
                )
                boxes[1].append(box)
            grids[1].insert(0, {"xs": xs, "ys": ys})
            result = bind_caption_grids(
                doc,
                structures,
                boxes,
                [1, 2],
                grids_for_page=lambda page: grids[page.number + 1],
            )
        self.assertEqual(result.issues, [])
        self.assertEqual(len(result.bindings), 8)
        for pair in result.bindings:
            self.assertEqual(pair["structure"]["id"], f"original-{pair['label']}")
            self.assertTrue(valid_caption_binding_evidence(binding(pair)))

    def test_completed_catalogue_role_cannot_skip_a_later_original_section(self):
        for title in (
            "Table 48. Intermediates",
            "Example 900. Intermediate preparation",
            "Example 900: Cell viability assay",
        ):
            with self.subTest(title=title):
                doc, structures, boxes, grids, pages = two_pages()
                with doc:
                    doc[0].insert_text((50, 260), title, fontsize=9)
                    result = bind_caption_grids(
                        doc,
                        structures,
                        boxes,
                        pages,
                        grids_for_page=lambda page, frames=grids: frames[
                            page.number + 1
                        ],
                    )
                self.assertFalse(
                    any(pair["structure"]["page_no"] == 2 for pair in result.bindings)
                )
                self.assertTrue(result.issues)

    def test_saved_continued_role_requires_the_complete_previous_original_tail(self):
        doc, structures, boxes, grids, pages = two_pages()
        with doc:
            result = bind_caption_grids(
                doc,
                structures,
                boxes,
                pages,
                grids_for_page=lambda page: grids[page.number + 1],
            )
        pair = next(p for p in result.bindings if p["label"] == "73C")
        original = binding(pair)
        self.assertTrue(valid_caption_binding_evidence(original))
        for mutate in (
            lambda link: link.pop("previous_tail"),
            lambda link: link["previous_tail"].update(chunks=[]),
            lambda link: link["previous_tail"].update(page_grids=[]),
            lambda link: link["previous_tail"].update(page_no=2),
        ):
            changed = copy.deepcopy(original)
            mutate(
                changed["exact_caption_evidence"]["ownership"]["caption_role"][
                    "continuation"
                ]
            )
            self.assertFalse(valid_caption_binding_evidence(changed))

    def test_nonfinal_exclusion_cannot_skip_a_new_original_table_before_next_page(self):
        doc, structures, boxes, grids = below_pages(
            role_title="Intermediates", tail_text="Table 48. Compounds"
        )
        with doc:
            result = bind_caption_grids(
                doc,
                structures,
                boxes,
                [1, 2],
                grids_for_page=lambda page: grids[page.number + 1],
            )
        self.assertTrue(result.exclusions)
        self.assertFalse(any(s["page_no"] == 2 for s in result.exclusions))
        self.assertTrue(result.issues)


if __name__ == "__main__":
    unittest.main()
