"""Generated multi-row ruled headers; original pixels and controlled OCR only."""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    measurement_text_cells,
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_header_columns import observe_header_columns
from patent_sar_extractor.core.activity_header_proof import valid_header_column
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_cells import observe_original_cell


class HeaderGridCellRowTests(unittest.TestCase):
    def observe(
        self, dpi=400, *, weak_unit=False, only_row=None, blank_id_row=False, depth=2
    ):
        native = fitz.open()
        self.addCleanup(native.close)
        page = native.new_page(width=390, height=230)
        page.insert_text((40, 35), "Table 47. Binding assay", fontsize=10)
        region = {
            "xs": [40, 140, 240, 350],
            "ys": [50 + 28 * row for row in range(depth + 2)],
        }
        for x in region["xs"]:
            page.draw_line((x, 50), (x, region["ys"][-1]))
        for y in region["ys"]:
            page.draw_line((40, y), (350, y))
        words = (
            (("Compound", "No."), ("IC50", "(nM)"), ("Dmax", "(%)"))
            if depth == 2
            else (
                ("Compound", "No.", ""),
                ("Kinase X", "IC50", "(nM)"),
                ("Degradation", "Dmax", "(%)"),
            )
        )
        for index, texts in enumerate(words):
            for row, text in enumerate(texts):
                if blank_id_row and index == 0 and row == 1:
                    continue
                page.insert_text(
                    (region["xs"][index] + 10, region["ys"][row] + 18),
                    text,
                    fontsize=10,
                )
        document = fitz.open()
        self.addCleanup(document.close)
        scanned = document.new_page(width=390, height=230)
        self.document = document
        scanned.insert_image(
            scanned.rect,
            stream=page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            ),
        )

        def literal_cell(target, bounds, kind, selected_dpi, _engine, normalize):
            text = page.get_textbox(fitz.Rect(bounds)).strip()
            confidence = 0.2 if weak_unit and "(nM)" in text else 0.99

            def engine(_image, *, use_det, use_cls):
                return ([], None) if use_det else ([[text, confidence]], None)

            return observe_original_cell(
                target, bounds, kind, selected_dpi, engine, normalize
            )

        self.literal_cell = literal_cell
        self.region = region
        self.source_tokens = SourceTokens(
            [
                {
                    **{
                        key: value
                        for key, value in token.items()
                        if key != "native_paint"
                    },
                    "source": "raster",
                    "confidence": 0.99,
                }
                for token in source_layout(page).native
            ],
            source_layout(scanned),
            tuple(scanned.rect),
        )

        with (
            patch(
                "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
                return_value=("rapidocr", None),
            ),
            patch(
                "patent_sar_extractor.core.activity_header_columns.observe_original_cell",
                side_effect=literal_cell,
            ),
        ):
            selected = (
                region
                if only_row is None
                else {"xs": region["xs"], "ys": region["ys"][only_row : only_row + 2]}
            )
            return observe_header_columns(
                scanned, selected, depth if only_row is None else 1, dpi
            )

    def test_three_physical_header_rows_preserve_qualifier_endpoint_and_unit(self):
        for dpi in (400, 600):
            view = self.observe(dpi, depth=3)
            self.assertEqual(
                view.matrix[-1],
                ["Compound\nNo.", "Kinase X\nIC50\n(nM)", "Degradation\nDmax\n(%)"],
            )
            self.assertEqual(view.verified, (True, True, True))
            for index, column in enumerate(view.columns):
                self.assertEqual(len(column["header_cells"]), 3)
                self.assertTrue(
                    valid_header_column(
                        column, index, view.matrix[-1][index], [40, 50, 350, 134], dpi
                    )
                )

    def test_individual_physical_header_rows_already_have_qualified_original_reads(
        self,
    ):
        for dpi in (400, 600):
            for row, expected in enumerate(
                (["Compound", "IC50", "Dmax"], ["No.", "(nM)", "(%)"])
            ):
                with self.subTest(dpi=dpi, row=row):
                    observed = self.observe(dpi, only_row=row)
                    self.assertEqual(observed.matrix[-1], expected)
                    self.assertEqual(observed.verified, (True, True, True))

    def test_separately_ruled_header_rows_keep_complete_literal_columns(self):
        for dpi in (400, 600):
            with self.subTest(dpi=dpi):
                result = self.observe(dpi)
                self.assertEqual(
                    result.matrix[-1], ["Compound\nNo.", "IC50\n(nM)", "Dmax\n(%)"]
                )
                self.assertEqual(result.verified, (True, True, True))
                for index, column in enumerate(result.columns):
                    self.assertTrue(
                        valid_header_column(
                            column,
                            index,
                            result.matrix[-1][index],
                            [40, 50, 350, 106],
                            dpi,
                        )
                    )

    def test_unqualified_unit_row_cannot_disappear_when_header_rows_are_joined(self):
        result = self.observe(weak_unit=True)
        self.assertIn("(nM)", result.matrix[-1][1])
        self.assertFalse(result.verified[1])
        self.assertFalse(
            valid_header_column(
                result.columns[1], 1, result.matrix[-1][1], [40, 50, 350, 106], 400
            )
        )

    def test_each_child_enters_the_same_original_replayer_without_starting_ocr(self):
        pair = [self.observe(dpi) for dpi in (400, 600)]
        payload = {
            "header_observations": {
                "controlled": {
                    "page_no": 1,
                    "observations": [{"columns": list(view.columns)} for view in pair],
                }
            }
        }
        cells = list(measurement_text_cells(payload))
        self.assertEqual(len(cells), 12)
        self.assertTrue(
            all(cell["method"].startswith("cell_ocr_") for _, cell in cells)
        )
        with patch(
            "patent_sar_extractor.core.table_cells.get_ocr_engine",
            side_effect=AssertionError("No model during original replay"),
        ):
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(self.document)
                ),
                [],
            )
        # A known white part of the original child, not a possibly black glyph.
        self.document[0].draw_rect(
            fitz.Rect(125, 60, 126, 61), color=None, fill=(0, 0, 0)
        )
        self.assertTrue(
            original_activity_source_errors(
                payload, open_original=lambda: nullcontext(self.document)
            )
        )

    def test_missing_reordered_or_relocated_children_cannot_qualify_a_column(self):
        view = self.observe()
        original = view.columns[1]
        for mutate in (
            lambda column: column["header_cells"].pop(),
            lambda column: column["header_cells"].reverse(),
            lambda column: column["grid_ys"].reverse(),
            lambda column: column["header_cells"][1]["bbox"].__setitem__(1, 79),
            lambda column: column.update(confidence=1),
            lambda column: column.update(raw_text="IC50 (uM)", text="IC50 (uM)"),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            self.assertFalse(
                valid_header_column(
                    changed, 1, changed["raw_text"], [40, 50, 350, 106], 400
                )
            )

    def test_blank_child_keeps_independent_original_absence_and_is_not_omitted(self):
        view = self.observe(blank_id_row=True)
        self.assertEqual(view.matrix[-1][0], "Compound")
        self.assertTrue(view.verified[0])
        column = view.columns[0]
        self.assertEqual(len(column["header_cells"]), 2)
        self.assertIn("empty_source", column["header_cells"][1])
        self.assertTrue(
            valid_header_column(column, 0, "Compound", [40, 50, 350, 106], 400)
        )
        changed = copy.deepcopy(column)
        changed["header_cells"][1].pop("empty_source")
        self.assertFalse(
            valid_header_column(changed, 0, "Compound", [40, 50, 350, 106], 400)
        )
