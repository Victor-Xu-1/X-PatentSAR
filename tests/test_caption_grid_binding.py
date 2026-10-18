import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_cells import CellReading


class CaptionGridBoundaryTests(unittest.TestCase):
    def control(self, *, title=True, bad_label=False, rival=False, direction="above"):
        doc = fitz.open()
        page = doc.new_page()
        xs, ys = [50, 180, 310], [100, 125, 205]
        if direction == "below":
            ys = [100, 180, 205]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        if title:
            page.insert_text((50, 85), "Table 47. Compounds")
        label_y = 117 if direction == "above" else 197
        page.insert_text(
            (70, label_y), "Compound S" if bad_label else "Compound 5", fontsize=9
        )
        page.insert_text((200, label_y), "Compound 6", fontsize=9)
        top = 140 if direction == "above" else 120
        boxes = [(80, top, 140, top + 35), (210, top, 270, top + 35)]
        structures = [
            {"id": str(i), "page_no": 1, "x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3]}
            for i, b in enumerate(boxes)
        ]
        if rival:
            structures.append({"id": "rival", "page_no": 1})
            boxes.append(None)
        return doc, {1: structures}, {1: boxes}

    def test_ambiguous_direction_cannot_fall_back_to_a_neighbor(self):
        doc, structures, boxes = self.control(title=False)
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual(result.bindings, [])
        self.assertEqual(result.pages, {1})
        self.assertTrue(result.issues)

    def test_explicit_below_catalog_remains_supported(self):
        doc, structures, boxes = self.control(direction="below")
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual([b["label"] for b in result.bindings], ["5", "6"])

    def test_original_title_starts_catalog_even_when_layout_lane_omits_it(self):
        for direction in ("above", "below"):
            with self.subTest(direction=direction):
                doc, structures, boxes = self.control(direction=direction)
                with doc:
                    page = doc[0]
                    layout = source_layout(page)
                    tokens = SourceTokens(
                        [token for token in layout.native if token["y"] >= 100],
                        layout,
                    )
                    result = bind_caption_grids(
                        doc,
                        structures,
                        boxes,
                        [1],
                        tokens_for_page=lambda _page: tokens,
                    )
                self.assertEqual(
                    [pair["label"] for pair in result.bindings],
                    ["5", "6"],
                    result.issues,
                )
                self.assertEqual(result.issues, [])

    def test_unlocated_rival_prevents_false_unique_owner(self):
        doc, structures, boxes = self.control(rival=True)
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual(result.bindings, [])

    def test_proved_caption_cells_are_read_even_when_page_ocr_did_not_parse_id(self):
        doc, structures, boxes = self.control(bad_label=True)

        def read(page, bounds, tokens, kind, native):
            value = "5" if bounds[0] < 100 else "6"
            return CellReading(
                value,
                bounds,
                [
                    {"method": "cell_ocr_400dpi", "text": value, "confidence": 0.99},
                    {"method": "cell_ocr_600dpi", "text": value, "confidence": 0.99},
                ],
                False,
            )

        with (
            doc,
            patch(
                "patent_sar_extractor.core.caption_grid_binding.read_cell",
                side_effect=read,
            ),
        ):
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual([b["label"] for b in result.bindings], ["5", "6"])
