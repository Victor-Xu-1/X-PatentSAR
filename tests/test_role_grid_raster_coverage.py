"""Real generated raster cells and production batching with a controlled text carrier."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import activity_grid_role_observation as observer
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from patent_sar_extractor.core.source_geometry import (
    SourceTokens,
    native_cell_text,
    source_layout,
)
from patent_sar_extractor.core.table_cells import CellRenderLimit, cell_image
from tests import test_role_grid_coverage as native_controls


class RasterRoleGridCoverageTests(unittest.TestCase):
    def source(self, count=32, *, footer=False, measurement=False):
        authored, grid, original, _identifiers = (
            native_controls.RoleGridCoverageTests.original(self, count)
        )
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=authored.rect.width, height=authored.rect.height)
        page.insert_image(
            page.rect,
            stream=authored.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            ),
        )
        if footer:
            page.insert_text(
                (30, page.rect.height - 10), "Native page footer", fontsize=7
            )
        if measurement:
            page.insert_text(
                (grid["xs"][-2] + 3, grid["ys"][-2] + 12), "IC50 = 3 nM", fontsize=7
            )
        layout = source_layout(page)
        tokens = SourceTokens(
            [{**token, "source": "raster", "confidence": 0.99} for token in original],
            layout,
            layout.raster_bounds,
        )
        return page, grid, tokens, original

    def observe(self, *, fail_tail=False, render_tail=False, footer=False):
        page, grid, tokens, original = self.source(footer=footer)
        current = {"text": "", "tail": False}
        frames = []

        def render(source, bounds, dpi):
            current["text"] = native_cell_text(original, bounds)
            current["tail"] = bounds[1] == grid["ys"][-2]
            if render_tail and current["tail"]:
                raise CellRenderLimit("Controlled last-window render refusal")
            frames.append((tuple(bounds), dpi))
            return cell_image(source, bounds, dpi)

        def reader(image, *, use_det, use_cls):
            # This supplies text only. Real source pixels, ink crops, line
            # geometry, paired views, batches and role proof are production code.
            confidence = 0.6 if fail_tail and current["tail"] else 0.99
            if use_det:
                height, width = image.shape[:2]
                return [
                    [
                        [
                            [0, 0],
                            [width - 1, 0],
                            [width - 1, height - 1],
                            [0, height - 1],
                        ],
                        current["text"],
                        confidence,
                    ]
                ], None
            return [[current["text"], confidence]], None

        failures = []
        with (
            patch.object(observer, "get_ocr_engine", return_value=("rapidocr", reader)),
            patch.object(observer, "cell_image", render),
        ):
            proof = observer.observe_characterization(
                page,
                grid,
                tokens,
                "Table J. Compound characterization",
                evidence_sink=failures,
            )
        return proof, failures, frames, grid

    def test_every_raster_cell_keeps_both_original_views_across_work_units(self):
        proof, failures, frames, grid = self.observe()
        self.assertIsNotNone(proof, [item["reason"] for item in failures])
        self.assertEqual(failures, [])
        self.assertEqual(len(frames), 198)
        self.assertEqual(len(set(frames)), len(frames))
        self.assertEqual(
            [view["method"] for view in proof["observations"]],
            ["cell_ocr_400dpi", "cell_ocr_600dpi"],
        )
        self.assertEqual(
            [len(view["cells"]) for view in proof["observations"]], [99, 99]
        )
        box = [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]]
        self.assertTrue(valid_role_scope({"bbox": box, "role_scope": proof}))
        changed = copy.deepcopy(proof)
        changed["observations"][1]["cells"].pop()
        self.assertFalse(valid_role_scope({"bbox": box, "role_scope": changed}))

        for mutation in ("method", "score", "part_score", "detection_score"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(proof)
                reading = changed["observations"][0]["cells"][-1]
                if mutation == "method":
                    changed["observations"][0]["method"] = []
                elif mutation == "score":
                    reading["confidence"] = 10**400
                elif mutation == "part_score":
                    reading["parts"][0]["confidence"] = 10**400
                else:
                    reading["detection_parts"].append(
                        {"text": "IC50", "confidence": 10**400}
                    )
                self.assertFalse(valid_role_scope({"bbox": box, "role_scope": changed}))

    def test_native_footer_does_not_turn_the_raster_table_into_native_cells(self):
        proof, failures, frames, grid = self.observe(footer=True)
        self.assertIsNotNone(proof, [item["reason"] for item in failures])
        self.assertEqual(len(frames), 198)
        self.assertTrue(
            all(value == "" for row in proof["native_hints"] for value in row)
        )
        self.assertEqual(proof["ys"], grid["ys"])

    def test_native_measurement_in_the_last_raster_row_vetoes_before_ocr(self):
        page, grid, tokens, _original = self.source(measurement=True)
        failures = []
        with patch.object(
            observer,
            "get_ocr_engine",
            side_effect=AssertionError(
                "Known native measurement must not be overruled"
            ),
        ):
            proof = observer.observe_characterization(
                page,
                grid,
                tokens,
                "Table J. Compound characterization",
                evidence_sink=failures,
            )
        self.assertIsNone(proof)
        self.assertEqual(
            [item["reason"] for item in failures], ["native_measurement_conflict"]
        )

    def test_weak_last_window_keeps_all_attempts_and_cannot_borrow_earlier_confidence(
        self,
    ):
        proof, failures, frames, _grid = self.observe(fail_tail=True)
        self.assertIsNone(proof)
        self.assertEqual(len(frames), 198)
        self.assertEqual(len(failures), 1)
        cells = failures[0]["source_cells"]
        self.assertEqual(
            [len(view["cells"]) for view in cells["observations"]], [99, 99]
        )
        for view in cells["observations"]:
            self.assertEqual(view["cells"][-1]["confidence"], 0.6)
            self.assertIn("NMR", view["cells"][-1]["raw_text"])

    def test_refused_tail_keeps_preceding_views_without_asserting_whole_coverage(self):
        proof, failures, _frames, grid = self.observe(render_tail=True)
        self.assertIsNone(proof)
        self.assertEqual([item["reason"] for item in failures], ["cell_render_limit"])
        source = failures[0]["source_cells"]
        self.assertEqual(source["ys"], grid["ys"])
        self.assertEqual(
            [len(view["cells"]) for view in source["observations"]], [96, 96]
        )
