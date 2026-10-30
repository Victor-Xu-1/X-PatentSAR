"""Generated original text frames; touched ink survives every reading view."""

import copy
import unittest
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

import fitz
import numpy as np

from patent_sar_extractor.core.cell_frame_proof import original_cell_frame_matches
from patent_sar_extractor.core.cell_header_lines import physical_line_frame
from patent_sar_extractor.core.cell_raster import (
    original_reading_image,
    render_cell_raster,
    valid_source_window,
)
from patent_sar_extractor.core.cell_text_chunks import observe_text_cell
from patent_sar_extractor.core.cell_text_proof import valid_text_reading
from patent_sar_extractor.core.cell_text_scope import text_scope
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine

BOUNDS = [0, 0, 200, 110]


def render_role_text_raster(page, bounds, dpi, *, maximum_row_height):
    return render_cell_raster(
        page, bounds, dpi, purpose="text", role_text_height=maximum_row_height
    )


def retained_reading(captured):
    return {
        "source_window": captured.source_window,
        "source_frame": captured.frame,
        "text_scope": text_scope(32, 32),
    }


@contextmanager
def generated_text_frame(edge, *, mutation=None, scan_dpi=None):
    document = fitz.open()
    try:
        page = document.new_page(width=200, height=110)
        page.draw_rect(fitz.Rect(3, 3, 197, 107), width=0.7)
        for index in range(8):
            page.insert_text(
                (26, 14 + 11 * index),
                f"Literal line {index + 1}: 7.23 (d, 2H)",
                fontsize=7,
            )
        if edge == "top" or mutation == "both":
            page.draw_line((26, 3), (26, 14), width=0.7)
        if edge == "bottom" or mutation == "both":
            page.draw_line((26, 91), (26, 107), width=0.7)
        if mutation == "side":
            page.draw_line((3, 55), (27, 55), width=0.7)
        elif mutation == "outward":
            page.draw_line((83, 2), (83, 4), width=0.2)
        if scan_dpi is None:
            yield document, page
        else:
            pixels = page.get_pixmap(dpi=scan_dpi, alpha=False).tobytes("png")
            with fitz.open() as scanned:
                scan = scanned.new_page(width=200, height=110)
                scan.insert_image(scan.rect, stream=pixels)
                yield scanned, scan
    finally:
        document.close()


def row_frame(image, dpi):
    return physical_line_frame(image, 0, dpi, maximum_row_height=32)


class PreservedCellFrameTests(unittest.TestCase):
    def test_actual_reader_keeps_weak_border_text_unaccepted_and_source_replay_inert(
        self,
    ):
        engine = get_ocr_engine()
        self.assertIsNotNone(engine)
        self.assertEqual(engine[0], "rapidocr")
        with generated_text_frame("top") as (_, page):
            for dpi in (400, 600):
                with self.subTest(dpi=dpi):
                    raster = render_role_text_raster(
                        page, BOUNDS, dpi, maximum_row_height=32
                    )
                    result = observe_text_cell(
                        raster.image, dpi, engine[1], maximum_row_height=32
                    )
                    result = replace(
                        result,
                        source_frame=raster.frame,
                        source_window=raster.source_window,
                    )
                    reading = result.evidence(dpi, BOUNDS)
                    self.assertEqual(len(result.parts), 8)
                    self.assertIn("Literal line 8", result.raw_text)
                    # Original pixels are replayable; this is NOT qualified text.
                    self.assertFalse(
                        valid_text_reading(
                            reading, BOUNDS, dpi, maximum_rows=32, maximum_row_height=32
                        )
                    )
                    with patch(
                        "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                        side_effect=AssertionError("Readback cannot infer text"),
                    ):
                        self.assertTrue(
                            original_cell_frame_matches(
                                reading, page, maximum_rows=32, maximum_row_height=32
                            )
                        )
                        self.assertFalse(original_cell_frame_matches(reading, page))

    def test_touched_horizontal_edge_is_kept_while_other_rules_are_separated(self):
        for edge in ("top", "bottom"):
            for dpi in (400, 600):
                with (
                    self.subTest(edge=edge, dpi=dpi),
                    generated_text_frame(edge) as (_, page),
                ):
                    captured = render_role_text_raster(
                        page, BOUNDS, dpi, maximum_row_height=32
                    )
                    self.assertEqual(captured.source_window["version"], 4)
                    self.assertEqual(captured.source_window["preserved_edge"], edge)
                    frame = row_frame(captured.image, dpi)
                    self.assertIsNotNone(frame)
                    self.assertGreater(len(frame["row_bounds"]), 1)
                    self.assertTrue(
                        valid_source_window(
                            captured.source_window, BOUNDS, dpi, captured.frame["shape"]
                        )
                    )
                    reading = retained_reading(captured)
                    np.testing.assert_array_equal(
                        original_reading_image(page, BOUNDS, dpi, reading),
                        captured.image,
                    )

    def test_differing_scanned_text_frames_use_the_same_pixel_source_recipe(self):
        for source_dpi in (144, 240):
            for edge in ("top", "bottom"):
                for dpi in (400, 600):
                    with (
                        self.subTest(source_dpi=source_dpi, edge=edge, dpi=dpi),
                        generated_text_frame(edge, scan_dpi=source_dpi) as (_, page),
                    ):
                        source = render_cell_raster(page, BOUNDS, dpi)
                        captured = render_role_text_raster(
                            page, BOUNDS, dpi, maximum_row_height=32
                        )
                        self.assertEqual(captured.source_window["version"], 4)
                        box = captured.source_window["read_bounds"]
                        x0, y0, x1, y1 = box
                        np.testing.assert_array_equal(
                            captured.image, source.image[y0:y1, x0:x1]
                        )
                        self.assertEqual(
                            captured.source_window["source_pixel_sha256"],
                            source.frame["pixel_sha256"],
                        )
                        self.assertGreater(
                            len(row_frame(captured.image, dpi)["row_bounds"]), 1
                        )
                        reading = retained_reading(captured)
                        np.testing.assert_array_equal(
                            original_reading_image(page, BOUNDS, dpi, reading),
                            captured.image,
                        )

    def test_historical_full_source_windows_replay_their_exact_old_recipe(self):
        for dpi in (400, 600):
            with self.subTest(dpi=dpi), generated_text_frame("top") as (_, page):
                previous = render_cell_raster(page, BOUNDS, dpi, purpose="text")
                self.assertEqual(previous.source_window["version"], 1)
                self.assertIsNone(previous.source_window["frame_strips"])
                self.assertEqual(row_frame(previous.image, dpi)["row_bounds"], [])
                reading = {
                    "source_window": previous.source_window,
                    "source_frame": previous.frame,
                }
                np.testing.assert_array_equal(
                    original_reading_image(page, BOUNDS, dpi, reading), previous.image
                )

    def test_ordinary_consumers_and_already_bounded_role_cells_remain_unchanged(self):
        with generated_text_frame("top") as (_, page):
            ordinary = render_cell_raster(page, BOUNDS, 400, purpose="text")
            bounded = render_role_text_raster(page, BOUNDS, 400, maximum_row_height=128)
            self.assertEqual(ordinary.source_window["version"], 1)
            self.assertEqual(bounded.source_window, ordinary.source_window)
            np.testing.assert_array_equal(bounded.image, ordinary.image)

    def test_pixel_callers_never_exclude_a_rectangular_diagram(self):
        with generated_text_frame("top") as (_, page):
            captured = render_cell_raster(page, BOUNDS, 400)
            self.assertEqual(captured.source_window["version"], 1)
            self.assertIsNone(captured.source_window["frame_strips"])
            self.assertEqual(
                captured.frame["pixel_sha256"],
                captured.source_window["source_pixel_sha256"],
            )

    def test_side_both_and_outward_unknown_ink_are_not_erased(self):
        for edge in ("top", "bottom"):
            for mutation in ("side", "both", "outward"):
                with (
                    self.subTest(edge=edge, mutation=mutation),
                    generated_text_frame(edge, mutation=mutation) as (_, page),
                ):
                    captured = render_cell_raster(page, BOUNDS, 400, purpose="text")
                    self.assertEqual(captured.source_window["version"], 1)
                    self.assertIsNone(captured.source_window["frame_strips"])

    def test_retained_window_and_original_source_cannot_be_forged(self):
        with generated_text_frame("top") as (document, page):
            captured = render_role_text_raster(page, BOUNDS, 400, maximum_row_height=32)
            self.assertEqual(captured.source_window["version"], 4)
            for mutation in ("edge", "bounds", "source", "strips", "version"):
                reading = copy.deepcopy(retained_reading(captured))
                window = reading["source_window"]
                if mutation == "edge":
                    window["preserved_edge"] = "bottom"
                elif mutation == "bounds":
                    window["read_bounds"][0] += 1
                elif mutation == "source":
                    window["source_pixel_sha256"] = "0" * 64
                elif mutation == "strips":
                    window["frame_strips"][0] = 0
                else:
                    window["version"] = True
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    original_reading_image(page, BOUNDS, 400, reading)
            with fitz.open(stream=document.tobytes(), filetype="pdf") as other:
                other[0].insert_text((70, 101), "Changed", fontsize=6)
                with self.assertRaises(ValueError):
                    original_reading_image(
                        other[0],
                        BOUNDS,
                        400,
                        retained_reading(captured),
                    )

    def test_malformed_proof_geometry_and_unknown_fields_refuse_without_coercion(self):
        with generated_text_frame("top") as (_, page):
            captured = render_role_text_raster(page, BOUNDS, 400, maximum_row_height=32)
            for field, value in (
                ("version", True),
                ("preserved_edge", []),
                ("preserved_edge", "left"),
                ("purpose", "pixels"),
                ("source_shape", [True, 10, 3]),
                ("source_shape", [[], 10, 3]),
                ("source_shape", [2, 3]),
                ("read_bounds", [0, 0, 1]),
                ("read_bounds", [False, 0, 2, 3]),
                ("frame_strips", [1, 0, 1, 0]),
                ("frame_strips", None),
                ("source_pixel_sha256", []),
                ("maximum_pixels", True),
                ("maximum_pixels", 8_000_001),
                ("maximum_pixels", 1),
                ("support", {}),
            ):
                window = {**captured.source_window, field: value}
                with self.subTest(field=field, value=value):
                    self.assertFalse(
                        valid_source_window(
                            window, BOUNDS, 400, captured.frame["shape"]
                        )
                    )
            for value in (True, 0, 129, "false", []):
                with self.subTest(recipe=value), self.assertRaises(ValueError):
                    render_cell_raster(
                        page, BOUNDS, 400, purpose="text", role_text_height=value
                    )

    def test_original_replay_rechecks_the_unbounded_trigger_and_exact_role_scope(self):
        with generated_text_frame("top") as (_, page):
            captured = render_role_text_raster(page, BOUNDS, 400, maximum_row_height=32)
            for mutation in ("missing_scope", "different_scope", "bounded_trigger"):
                reading = copy.deepcopy(retained_reading(captured))
                if mutation == "missing_scope":
                    reading.pop("text_scope")
                elif mutation == "different_scope":
                    reading["text_scope"] = text_scope(32, 12)
                else:
                    reading["text_scope"] = text_scope(32, 128)
                    reading["source_window"]["role_text_height"] = 128
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    original_reading_image(page, BOUNDS, 400, reading)
            for dpi in (True, [], {}, "400", 450):
                with self.subTest(dpi=dpi), self.assertRaises(ValueError):
                    render_role_text_raster(page, BOUNDS, dpi, maximum_row_height=32)

    def test_lower_original_render_budget_is_recorded_and_replayed_without_expansion(
        self,
    ):
        with generated_text_frame("top") as (_, page):
            raster = render_cell_raster(
                page,
                BOUNDS,
                400,
                purpose="text",
                role_text_height=32,
                maximum_pixels=1_000_000,
            )
            self.assertEqual(raster.source_window["version"], 4)
            self.assertEqual(raster.source_window["maximum_pixels"], 1_000_000)
            np.testing.assert_array_equal(
                original_reading_image(page, BOUNDS, 400, retained_reading(raster)),
                raster.image,
            )


if __name__ == "__main__":
    unittest.main()
