"""Original diagram rows and their later captions may straddle a page break."""

import copy
import json
import unittest

import fitz

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_observation import owns_caption_frame
from patent_sar_extractor.core.table_geometry import page_tokens
from patent_sar_extractor.core.visible_structure_binding import bind_visible_captions
from tests.test_caption_role_continuation import binding


def below_pages(
    *,
    columns=2,
    gap=False,
    shift=0,
    next_title=None,
    tail_text=None,
    label_only=False,
    extra_grid=False,
    unknown_rival=False,
    label_prefix="",
    table_number=47,
    role_title="Compounds",
):
    doc = fitz.open()
    by_page, boxes, grids = {}, {}, {}
    for number, ys, labels, drawings in (
        (
            1,
            [100, 180, 205, 285],
            [(1, ("41A", "89B"))],
            [(0, ("41A", "89B")), (2, ("7E", "8E"))],
        ),
        (
            2,
            [50, 75, 155, 180],
            [(0, ("7E", "8E")), (2, ("73C", "104D"))],
            [(1, ("73C", "104D"))],
        ),
    ):
        if number == 2 and gap:
            doc.new_page(width=380, height=360)
            number = 3
        xs = [
            edge + (shift if number > 1 else 0)
            for edge in [50, 180, 310][: columns + 1]
        ]
        if number > 1 and label_only:
            ys, labels, drawings = [50, 75], [(0, ("7E", "8E"))], []
        page = doc.new_page(width=380, height=360)
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        if number == 1:
            page.insert_text(
                (50, 85), f"Table {table_number}. {role_title}", fontsize=10
            )
            if tail_text:
                page.insert_text((50, 308), tail_text, fontsize=9)
        elif next_title:
            page.insert_text((50, 35), next_title, fontsize=9)
        for row, ids in labels:
            for col, label in enumerate(ids[:columns]):
                page.insert_text(
                    (xs[col] + 15, ys[row] + 17),
                    f"Compound {label_prefix}{label}",
                    fontsize=9,
                )
        by_page[number], boxes[number] = [], []
        for row, ids in drawings:
            for col, label in enumerate(ids[:columns]):
                box = (xs[col] + 20, ys[row] + 15, xs[col] + 80, ys[row + 1] - 15)
                by_page[number].append(
                    {
                        "id": f"original-{label_prefix}{label}",
                        "page_no": number,
                        **dict(zip(("x0", "y0", "x1", "y1"), box)),
                    }
                )
                boxes[number].append(box)
        grids[number] = [{"xs": xs, "ys": ys}]
        if number == 1 and extra_grid:
            extra = {"xs": xs, "ys": [315, 335]}
            for x in xs:
                page.draw_line((x, 315), (x, 335))
            for y in extra["ys"]:
                page.draw_line((xs[0], y), (xs[-1], y))
            grids[number].append(extra)
        if number == 1 and unknown_rival:
            by_page[number].append({"id": "unlocated", "page_no": number})
            boxes[number].append(None)
    return doc, by_page, boxes, grids


class CaptionPageBoundaryTests(unittest.TestCase):
    def observe(self, **options):
        doc, structures, boxes, grids = below_pages(**options)
        with doc:
            return bind_caption_grids(
                doc,
                structures,
                boxes,
                range(1, len(doc) + 1),
                grids_for_page=lambda page: grids.get(page.number + 1, []),
            )

    def test_below_captions_bind_previous_page_tail_not_next_page_diagrams(self):
        doc, structures, boxes, grids = below_pages()
        with doc:
            result = bind_caption_grids(
                doc,
                structures,
                boxes,
                [1, 2],
                grids_for_page=lambda page: grids[page.number + 1],
            )
        self.assertEqual(
            {(pair["label"], pair["structure"]["id"]) for pair in result.bindings},
            {
                (label, f"original-{label}")
                for label in ("41A", "89B", "7E", "8E", "73C", "104D")
            },
        )
        self.assertEqual(result.issues, [])
        for pair in result.bindings:
            self.assertTrue(valid_caption_binding_evidence(binding(pair)))
        cross = next(pair for pair in result.bindings if pair["label"] == "7E")
        self.assertEqual(cross["structure"]["page_no"], 1)
        self.assertEqual(cross["label_page_no"], 2)

    def test_continued_frame_role_is_shared_only_for_identical_current_source_facts(
        self,
    ):
        doc, structures, boxes, grids = below_pages()
        with doc:
            result = bind_caption_grids(
                doc,
                structures,
                boxes,
                [1, 2],
                grids_for_page=lambda page: grids[page.number + 1],
            )
            page, region = doc[1], grids[2][0]
            tokens = page_tokens(page, dpi=200, allow_tesseract=False)
            role = result.roles[(2, (50, 50, 310, 180))]
            self.assertFalse(
                owns_caption_frame(page, region, grids[2], tokens, boxes[2])
            )
            self.assertTrue(
                owns_caption_frame(
                    page,
                    region,
                    grids[2],
                    tokens,
                    boxes[2],
                    original_role=role,
                )
            )
            for key, value in (
                ("table_key", "TABLE48"),
                ("sources", []),
                ("page_no", 9),
            ):
                changed = copy.deepcopy(role)
                changed[key] = value
                self.assertFalse(
                    owns_caption_frame(
                        page,
                        region,
                        grids[2],
                        tokens,
                        boxes[2],
                        original_role=changed,
                    )
                )

    def test_single_column_and_small_scan_shift_keep_literal_original_owners(self):
        for options in ({"columns": 1}, {"shift": 2}):
            with self.subTest(options=options):
                result = self.observe(**options)
                self.assertEqual(result.issues, [])
                self.assertTrue(result.bindings)
                self.assertTrue(
                    all(
                        pair["structure"]["id"] == f"original-{pair['label']}"
                        and valid_caption_binding_evidence(binding(pair))
                        for pair in result.bindings
                    )
                )

    def test_labels_only_next_page_remains_in_complete_source_inventory(self):
        doc, structures, _boxes, grids = below_pages(label_only=True)
        with doc:
            pairs = bind_visible_captions(
                doc,
                [row for rows in structures.values() for row in rows],
                None,
                source_pages=[0, 1],
                grids_for_page=lambda page: grids[page.number + 1],
            )
        self.assertEqual({pair.label for pair in pairs}, {"41A", "89B", "7E", "8E"})
        cross = next(pair for pair in pairs if pair.label == "7E")
        self.assertEqual((cross.structure["page_no"], cross.label_page_no), (1, 2))

    def test_real_raster_grid_and_cell_readers_preserve_the_same_cross_page_owners(
        self,
    ):
        original, structures, boxes, _grids = below_pages()
        with original, fitz.open() as raster:
            for page in original:
                pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                target = raster.new_page(width=page.rect.width, height=page.rect.height)
                target.insert_image(target.rect, stream=pixels.tobytes("png"))
            result = bind_caption_grids(raster, structures, boxes, [1, 2])
        self.assertEqual(result.issues, [])
        self.assertEqual(len(result.bindings), 6)
        for pair in result.bindings:
            self.assertEqual(pair["structure"]["id"], f"original-{pair['label']}")
            self.assertTrue(
                any(row["method"] == "cell_ocr_400dpi" for row in pair["observations"])
            )
            self.assertTrue(
                valid_caption_binding_evidence(json.loads(json.dumps(binding(pair))))
            )

    def test_page_gap_new_context_intervening_grid_and_unknown_rival_stop_bridge(self):
        for options in (
            {"gap": True},
            {"shift": 12},
            {"next_title": "Table 48. Continued"},
            {"next_title": "Table 47. Intermediates"},
            {"tail_text": "Table 48. Intermediates"},
            {"tail_text": "Example 900. Intermediate preparation"},
            {"tail_text": "Intermediate 900"},
            {"tail_text": "Example 900: Cell viability assay"},
            {"extra_grid": True},
            {"unknown_rival": True},
        ):
            with self.subTest(options=options):
                result = self.observe(**options)
                self.assertFalse(
                    any(
                        pair["label"] in {"7E", "8E"}
                        and pair["structure"]["page_no"] == 1
                        for pair in result.bindings
                    )
                )
                self.assertTrue(result.issues)

    def test_saved_boundary_cannot_omit_change_or_move_either_original_context(self):
        cross = next(pair for pair in self.observe().bindings if pair["label"] == "7E")
        original = binding(cross)
        self.assertTrue(valid_caption_binding_evidence(original))
        for change in (
            lambda o: o.pop("page_boundary"),
            lambda o: o.update(direction="above"),
            lambda o: o["page_boundary"].update(version=True),
            lambda o: o["page_boundary"].update(unproved=True),
            lambda o: o["page_boundary"]["other_role"].update(page_no=9),
            lambda o: o["page_boundary"]["previous_tail"].update(chunks=[]),
            lambda o: o["page_boundary"]["previous_tail"].update(
                window=[0, 285, 380, 320]
            ),
            lambda o: o["page_boundary"]["previous_tail"].update(page_grids=[]),
            lambda o: o["page_boundary"]["previous_tail"].update(page_no=True),
        ):
            item = copy.deepcopy(original)
            change(item["exact_caption_evidence"]["ownership"])
            self.assertFalse(valid_caption_binding_evidence(item))
        same_page = binding(self.observe().bindings[0])
        same_page["exact_caption_evidence"]["ownership"]["page_boundary"] = (
            copy.deepcopy(
                original["exact_caption_evidence"]["ownership"]["page_boundary"]
            )
        )
        self.assertFalse(valid_caption_binding_evidence(same_page))


if __name__ == "__main__":
    unittest.main()
