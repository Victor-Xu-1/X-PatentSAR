"""Larger original characterization text is not an assay header or a new heading."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import activity_grid_role_observation as observer
from patent_sar_extractor.core import cell_raster
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from patent_sar_extractor.core.binding_source_regions import reference_cell
from patent_sar_extractor.core.cell_text_proof import valid_text_reading
from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.role_text_sources import role_text_cells
from patent_sar_extractor.core.source_geometry import (
    SourceTokens,
    native_cell_text,
    source_layout,
)


class RoleTextTypographyTests(unittest.TestCase):
    def source(self, *, weak=False, endpoint=False, recovery=False):
        authored = fitz.open()
        self.addCleanup(authored.close)
        page = authored.new_page(width=900, height=300)
        xs, ys = [20, 150, 440, 880], [30, 60, 250]
        matrix = [
            ["Compound No.", "Preparation", "Characterization"],
            [
                "Compound 076C",
                "Prepared according to Compound 044A",
                "1H NMR (500 MHz) 7.01 ppm\n1H NMR (500 MHz) 7.23 ppm\n1H NMR (500 MHz) 7.45 ppm",
            ],
        ]
        if endpoint:
            matrix[1][2] += "\nIC50 = 4 nM"
        for row, values in enumerate(matrix):
            for column, text in enumerate(values):
                for index, line in enumerate(text.splitlines()):
                    page.insert_text(
                        (
                            xs[column] + 4,
                            ys[row] + (30 + 35 * index if row and column == 2 else 18),
                        ),
                        line,
                        fontsize=18 if row and column == 2 else 8,
                    )
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        original = source_layout(page)
        scan = fitz.open()
        self.addCleanup(scan.close)
        raster = scan.new_page(width=900, height=300)
        raster.insert_image(
            raster.rect, stream=page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png")
        )
        layout = source_layout(raster)
        tokens = SourceTokens(
            [
                {**word, "source": "raster", "confidence": 0.99}
                for word in original.native
            ],
            layout,
            layout.raster_bounds,
        )
        originals = SourceTokens(original.native, original)
        current = {"lines": [], "index": 0}
        render_original = cell_raster.render_cell_raster
        from tests.test_auxiliary_cell_evidence import ControlledAuxiliary

        auxiliary_reader = ControlledAuxiliary()
        observe_auxiliary = auxiliary_reader.observe
        auxiliary_index = {"value": 0}

        def render(source, bounds, dpi, **options):
            current["lines"] = native_cell_text(originals, bounds).splitlines()
            current["index"] = 0
            auxiliary_index["value"] = 0
            return render_original(source, bounds, dpi, **options)

        def recovered(image):
            lines = current["lines"]
            text = lines[auxiliary_index["value"] % len(lines)] if lines else ""
            auxiliary_index["value"] += 1
            result = observe_auxiliary(image)
            result["text"] = text
            return result

        auxiliary_reader.observe = recovered

        def reader(image, *, use_det, use_cls):
            if use_det:
                return [], None
            lines = current["lines"]
            text = lines[current["index"] % len(lines)] if lines else ""
            current["index"] += 1
            return [[text, 0.2 if weak else 0.99]], None

        failures = []
        with (
            patch.object(observer, "render_cell_raster", render),
            patch.object(cell_raster, "render_cell_raster", render),
            patch.object(observer, "get_ocr_engine", return_value=("rapidocr", reader)),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=auxiliary_reader if recovery else None,
            ) as auxiliary,
        ):
            proof = observer.observe_characterization(
                raster,
                {"xs": xs, "ys": ys},
                tokens,
                "Table Q. Compound characterization",
                evidence_sink=failures,
            )
        return raster, proof, failures, auxiliary

    def test_heading_inventory_uses_the_whole_proved_table_role(self):
        from patent_sar_extractor.core.binding_source_headings import (
            observed_heading_blocks,
        )

        page, proof, failures, _auxiliary = self.source()
        self.assertIsNotNone(proof, [f["reason"] for f in failures])
        region = {
            "page_no": 1,
            "bbox": [20, 30, 880, 250],
            "region_id": "controlled-region",
            "role_scope": proof,
        }
        line = {
            "y0": 69,
            "y1": 82,
            "text": "Compound 076C",
            "bbox": [24, 69, 120, 82],
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        sections = []
        with patch(
            "patent_sar_extractor.core.binding_source_headings.observe_heading",
            side_effect=AssertionError(
                "A proved table reference is not a procedure heading"
            ),
        ):
            blocks = observed_heading_blocks(
                page.parent,
                [0],
                {},
                source_line_map={0: [line]},
                source_sections=sections,
                source_regions={0: [region]},
            )
        self.assertEqual(blocks, [])
        self.assertEqual(
            [section["role"] for section in sections], ["characterization_reference"]
        )

    def test_weak_larger_rows_can_recover_only_inside_the_recorded_scope(self):
        from patent_sar_extractor.core.text_ocr.cell_proof import (
            replay_auxiliary_cell,
            valid_auxiliary_cell,
        )

        page, proof, failures, _auxiliary = self.source(weak=True, recovery=True)
        self.assertIsNotNone(proof, [f["reason"] for f in failures])
        reading = proof["observations"][0]["cells"][-1]
        self.assertEqual(reading["auxiliary_text"]["maximum_row_height"], 32)
        self.assertTrue(valid_auxiliary_cell(reading, 400))
        self.assertTrue(replay_auxiliary_cell(reading, page))
        for limit in (12, 128, 32.0, True):
            altered = copy.deepcopy(reading)
            altered["auxiliary_text"]["maximum_row_height"] = limit
            self.assertFalse(valid_auxiliary_cell(altered, 400))
        self.assertFalse(valid_text_reading(reading, reading["bbox"], 400))

    def test_larger_original_table_text_proves_reference_not_procedure_heading(self):
        page, proof, failures, auxiliary = self.source()
        self.assertIsNotNone(proof, [f["reason"] for f in failures])
        auxiliary.assert_not_called()
        region = {
            "page_no": 1,
            "bbox": [20, 30, 880, 250],
            "region_id": "controlled-region",
            "role_scope": json.loads(json.dumps(proof)),
        }
        self.assertTrue(valid_role_scope(region))
        line = {
            "text": "Compound 076C",
            "bbox": [24, 69, 120, 82],
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        self.assertEqual(reference_cell(line, [region])["reference_kind"], "identifier")
        cells = list(role_text_cells({"coverage": {"regions": [region]}}))
        self.assertEqual(len(cells), 12)
        self.assertEqual(original_role_source_errors(page.parent, cells), [])
        reading = proof["observations"][0]["cells"][-1]
        self.assertFalse(valid_text_reading(reading, reading["bbox"], 400))
        self.assertTrue(
            valid_text_reading(
                reading,
                reading["bbox"],
                400,
                maximum_rows=32,
                maximum_row_height=32,
                allow_chunks=True,
            )
        )

    def test_weak_text_and_known_endpoint_still_refuse_a_characterization_role(self):
        for options in ({"weak": True}, {"endpoint": True}):
            with self.subTest(options=options):
                _page, proof, failures, _auxiliary = self.source(**options)
                self.assertIsNone(proof)
                self.assertTrue(failures)

    def test_removed_or_forged_typography_scope_cannot_replay_or_qualify(self):
        page, proof, failures, _auxiliary = self.source()
        self.assertIsNotNone(proof, [f["reason"] for f in failures])
        for change in ("missing", "larger", "fractional", "rows"):
            with self.subTest(change=change):
                altered = copy.deepcopy(proof)
                reading = altered["observations"][0]["cells"][-1]
                if change == "missing":
                    del reading["text_scope"]
                elif change == "larger":
                    reading["text_scope"]["maximum_row_height"] = 128
                elif change == "fractional":
                    reading["text_scope"]["maximum_row_height"] = 32.0
                else:
                    reading["text_scope"]["maximum_rows"] = 8
                region = {
                    "page_no": 1,
                    "bbox": [20, 30, 880, 250],
                    "role_scope": altered,
                }
                self.assertFalse(valid_role_scope(region))
                with self.assertRaisesRegex(ValueError, "typography"):
                    list(role_text_cells({"coverage": {"regions": [region]}}))
        region = {"page_no": 1, "bbox": [20, 30, 880, 250], "role_scope": proof}
        cells = list(role_text_cells({"coverage": {"regions": [region]}}))
        page.insert_text((445, 230), "Unexpected original ink", fontsize=8)
        self.assertTrue(original_role_source_errors(page.parent, cells))


if __name__ == "__main__":
    unittest.main(verbosity=2)
