"""Unresolved closed-cell text must not silently become post-table context.

Generated source images and controlled literal OCR packets only; no model/private
PDF processing. Unresolved labels remain unresolved, not inferred from neighbours.
"""

import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_cells import _normalize, observe_original_cell
from tests.test_caption_role_continuation import binding, two_pages


class UnresolvedCaptionBoundaryTests(unittest.TestCase):
    def observe(
        self,
        *,
        unknown_after_table=False,
        after_table=None,
        note_baseline=228,
        padding=2,
    ):
        native, structures, boxes, grids, pages = two_pages(split=True)
        self.addCleanup(native.close)
        native[0].insert_text((65, note_baseline), "uncertain note", fontsize=6)
        native[0].insert_text((290, 800), "22", fontsize=9)
        if unknown_after_table or after_table:
            native[0].insert_text(
                (50, 254), after_table or "Unread subsequent source", fontsize=9
            )
        document = fitz.open()
        self.addCleanup(document.close)
        self.document = document
        for page in native:
            document.new_page(
                width=page.rect.width, height=page.rect.height
            ).insert_image(
                page.rect,
                stream=page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                    "png"
                ),
            )

        def tokens(page):
            source = [
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key != "native_paint"
                    },
                    "source": "raster",
                    "confidence": 0.99,
                }
                for item in source_layout(native[page.number]).native
            ]
            if page.number == 0:
                for item in source:
                    if item["text"] in {"uncertain", "note"}:
                        # The original glyph is inside the last closed cell;
                        # the independent layout proposal has a padded box.
                        item["bbox"] = [
                            *item["bbox"][:3],
                            grids[1][0]["ys"][-1] + padding,
                        ]
                    elif unknown_after_table and item["text"] in {
                        "Unread",
                        "subsequent",
                        "source",
                    }:
                        # A genuinely unqualified outside source, not a fully
                        # readable ordinary table footnote with an English label.
                        item["confidence"] = 0.2
            return SourceTokens(source, source_layout(page), tuple(page.rect))

        def controlled_cell(page, bounds, kind, dpi):
            literal = native[page.number].get_textbox(fitz.Rect(bounds)).strip()

            def engine(_image, *, use_det, use_cls):
                return ([], None) if use_det else ([[literal, 0.99]], None)

            return observe_original_cell(page, bounds, kind, dpi, engine, _normalize)

        with (
            patch(
                "patent_sar_extractor.core.table_cells._ocr_cell",
                side_effect=controlled_cell,
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            ),
        ):
            return bind_caption_grids(
                document,
                structures,
                boxes,
                pages,
                grids_for_page=lambda page: grids[page.number + 1],
                tokens_for_page=tokens,
            )

    def test_unknown_closed_caption_cannot_poison_the_next_known_source(self):
        result = self.observe()
        labels = {pair["label"] for pair in result.bindings}
        self.assertIn("73C", labels)
        self.assertIn("104D", labels)
        self.assertNotIn("7E", labels)
        self.assertTrue(
            result.issues, "The unknown label must remain explicitly unresolved"
        )
        for pair in result.bindings:
            self.assertTrue(valid_caption_binding_evidence(binding(pair)))

    def test_unknown_text_outside_the_closed_grid_still_blocks_continuation(self):
        result = self.observe(unknown_after_table=True)
        self.assertFalse({"73C", "104D"} & {pair["label"] for pair in result.bindings})
        self.assertTrue(result.issues)

    def test_new_unknown_table_title_outside_the_grid_still_blocks(self):
        result = self.observe(after_table="Table 99. Unknown catalogue")
        self.assertFalse({"73C", "104D"} & {pair["label"] for pair in result.bindings})
        self.assertTrue(result.issues)

    def test_explicit_nonfinal_outside_source_still_blocks(self):
        result = self.observe(after_table="Intermediate 88")
        self.assertFalse({"73C", "104D"} & {pair["label"] for pair in result.bindings})
        self.assertTrue(result.issues)

    def test_actual_note_ink_over_the_closed_border_is_not_a_padding_excuse(self):
        result = self.observe(note_baseline=232)
        self.assertFalse({"73C", "104D"} & {pair["label"] for pair in result.bindings})
        self.assertTrue(result.issues)

    def test_qualified_ordinary_footnote_keeps_existing_source_policy(self):
        result = self.observe(after_table="Structures continued on following page.")
        self.assertTrue({"73C", "104D"} <= {pair["label"] for pair in result.bindings})
        self.assertNotIn("7E", {pair["label"] for pair in result.bindings})

    def test_over_bound_layout_padding_cannot_request_unbounded_support(self):
        result = self.observe(padding=8)
        self.assertFalse({"73C", "104D"} & {pair["label"] for pair in result.bindings})
        self.assertTrue(result.issues)
