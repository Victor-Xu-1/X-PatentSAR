"""Actual generated PDF capture, device coordinates and original-window proof."""

import copy
import hashlib
import unittest
from dataclasses import replace
from unittest.mock import patch

import fitz
import numpy as np
from test_cell_boundary_ownership import BOUNDS, ink, pixels, word_at_edge

from patent_sar_extractor.core.cell_frame_proof import original_cell_frame_matches
from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.cell_raster import (
    cell_pixel_rect,
    cell_window_origin,
    render_cell_raster,
    valid_source_window,
)
from patent_sar_extractor.core.cell_rendering import CellRenderLimit
from patent_sar_extractor.core.table_cells import CellRenderLimit as ExistingRenderLimit


class CellRasterTests(unittest.TestCase):
    def test_contiguous_and_cropped_views_keep_exact_raw_byte_digests(self):
        with word_at_edge("DC50 nM", "top", 4, 400) as (_, page):
            captured = render_cell_raster(page, BOUNDS, 400, purpose="text")
            self.assertEqual(
                captured.frame["pixel_sha256"],
                hashlib.sha256(captured.image.tobytes()).hexdigest(),
            )
        with fitz.open() as document:
            page = document.new_page(width=180, height=90)
            page.draw_rect(fitz.Rect(3, 3, 177, 87), color=(0, 0, 0), width=1)
            page.insert_text((30, 45), "37B", fontsize=8)
            captured = render_cell_raster(page, [0, 0, 180, 90], 400, purpose="text")
            self.assertIsNotNone(captured.source_window["frame_strips"])
            self.assertEqual(
                captured.frame["pixel_sha256"],
                hashlib.sha256(captured.image.tobytes()).hexdigest(),
            )

    def reading(self, page, dpi):
        raster = render_cell_raster(page, BOUNDS, dpi, purpose="text")
        literal_reader = lambda *_args, **_kwargs: ([["DC50 nM", 0.999]], None)
        reading = observe_cell(
            raster.image, "header", dpi, literal_reader, lambda raw, _kind: raw.strip()
        )
        return replace(
            reading, source_frame=raster.frame, source_window=raster.source_window
        ).evidence(dpi, BOUNDS)

    def test_existing_original_replayer_checks_full_source_and_reading_window(self):
        for dpi in (400, 600):
            with (
                self.subTest(dpi=dpi),
                word_at_edge("DC50 nM", "left", 0.5, dpi) as (document, page),
            ):
                reading = self.reading(page, dpi)
                self.assertTrue(original_cell_frame_matches(reading, page))
                for field in (
                    "source_digest",
                    "window_shape",
                    "view_digest",
                    "omitted",
                ):
                    changed = copy.deepcopy(reading)
                    if field == "source_digest":
                        changed["source_window"]["source_pixel_sha256"] = "0" * 64
                    elif field == "window_shape":
                        changed["source_window"]["source_shape"][0] += 1
                    elif field == "view_digest":
                        changed["source_frame"]["pixel_sha256"] = "0" * 64
                    else:
                        del changed["source_window"]
                    with self.subTest(field=field):
                        self.assertFalse(original_cell_frame_matches(changed, page))
                with fitz.open(stream=document.tobytes(), filetype="pdf") as other:
                    other[0].insert_text((160, 130), "Added", fontsize=8)
                    self.assertFalse(original_cell_frame_matches(reading, other[0]))

    def test_complete_generated_edge_text_has_original_and_read_view_identity(self):
        for dpi in (400, 600):
            for edge in ("left", "right", "top", "bottom"):
                with (
                    self.subTest(dpi=dpi, edge=edge),
                    word_at_edge("<0.5 nM", edge, 0.5, dpi) as (_, page),
                ):
                    result = render_cell_raster(page, BOUNDS, dpi)
                    self.assertEqual(
                        int(ink(result.image).sum()), int(ink(pixels(page, dpi)).sum())
                    )
                    self.assertTrue(
                        valid_source_window(
                            result.source_window, BOUNDS, dpi, result.frame["shape"]
                        )
                    )
                    self.assertIsNone(result.source_window["frame_strips"])
                    self.assertEqual(
                        result.frame["pixel_sha256"],
                        result.source_window["source_pixel_sha256"],
                    )

    def test_capture_requires_no_text_engine_and_does_not_modify_its_original(self):
        with word_at_edge("37B", "bottom", 0.5, 400) as (document, page):
            original = document.tobytes(no_new_id=True)
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Geometry may not load OCR"),
            ):
                render_cell_raster(page, BOUNDS, 400)
            self.assertEqual(document.tobytes(no_new_id=True), original)

    def test_changed_original_keeps_geometry_but_cannot_reuse_source_digests(self):
        with word_at_edge("DC50 pM", "top", 4, 400) as (document, page):
            observed = render_cell_raster(page, BOUNDS, 400)
            with fitz.open(stream=document.tobytes(), filetype="pdf") as other:
                other[0].insert_text((150, 110), "Changed", fontsize=8)
                fresh = render_cell_raster(other[0], BOUNDS, 400)
            self.assertEqual(
                observed.source_window["read_bounds"],
                fresh.source_window["read_bounds"],
            )
            self.assertNotEqual(observed.source_window, fresh.source_window)
            self.assertNotEqual(observed.frame, fresh.frame)

    def test_coordinates_are_the_exact_device_origin_without_the_old_inset(self):
        with fitz.open() as document:
            page = document.new_page(width=240, height=190)
            bounds = [20.35, 25.45, 140.75, 130.95]
            for rotation in (0, 90, 180, 270):
                page.set_rotation(rotation)
                for dpi in (400, 600):
                    with self.subTest(rotation=rotation, dpi=dpi):
                        observed = render_cell_raster(page, bounds, dpi)
                        extent = cell_pixel_rect(bounds, dpi)
                        self.assertEqual(
                            cell_window_origin(
                                observed.source_window,
                                bounds,
                                dpi,
                                observed.frame["shape"],
                            ),
                            [extent.x0 * 72 / dpi, extent.y0 * 72 / dpi],
                        )

    def test_window_geometry_rejects_omission_foreign_shapes_and_unproved_crops(self):
        with word_at_edge("IC50 nM", "right", 2, 400) as (_, page):
            observed = render_cell_raster(page, BOUNDS, 400)
            for mutation in ("version", "source_shape", "extra", "crop", "digest"):
                changed = copy.deepcopy(observed.source_window)
                if mutation == "version":
                    changed["version"] = True
                elif mutation == "source_shape":
                    changed["source_shape"][0] += 1
                elif mutation == "extra":
                    changed["unknown"] = "field"
                elif mutation == "crop":
                    changed["read_bounds"][0] += 1
                else:
                    changed["source_pixel_sha256"] = "not-a-digest"
                with self.subTest(mutation=mutation):
                    self.assertFalse(
                        valid_source_window(
                            changed, BOUNDS, 400, observed.frame["shape"]
                        )
                    )
            self.assertFalse(
                valid_source_window(observed.source_window, BOUNDS, 400, [True, 1, 3])
            )

    def test_invalid_and_over_budget_frames_fail_before_rendering(self):
        self.assertIs(ExistingRenderLimit, CellRenderLimit)
        with fitz.open() as document:
            page = document.new_page(width=300, height=220)
            with patch(
                "patent_sar_extractor.core.cell_raster.original_cell_pixmap"
            ) as renderer:
                with self.assertRaises(CellRenderLimit):
                    render_cell_raster(page, BOUNDS, 400, maximum_pixels=10)
                for bounds, dpi in (
                    (BOUNDS, True),
                    ([0, 0, float("nan"), 10], 400),
                    ([-1, 0, 20, 30], 400),
                    ([0, 0, 301, 220], 400),
                ):
                    with (
                        self.subTest(bounds=bounds, dpi=dpi),
                        self.assertRaises(ValueError),
                    ):
                        render_cell_raster(page, bounds, dpi)
                renderer.assert_not_called()

    def test_actual_closed_frame_has_an_explicit_replayable_coordinate_shift(self):
        with fitz.open() as source:
            page = source.new_page(width=180, height=90)
            page.draw_rect(fitz.Rect(3, 3, 177, 87), color=(0, 0, 0), width=1)
            page.insert_text((30, 45), "37B", fontsize=8)
            observed = render_cell_raster(page, [0, 0, 180, 90], 400, purpose="text")
            self.assertTrue(
                valid_source_window(
                    observed.source_window,
                    [0, 0, 180, 90],
                    400,
                    observed.frame["shape"],
                )
            )
            self.assertIsNotNone(
                observed.source_window["frame_strips"],
                "An ordinary isolated original rectangular frame is supported",
            )
            self.assertGreater(int(np.count_nonzero(ink(observed.image))), 0)
            repeat = render_cell_raster(page, [0, 0, 180, 90], 400, purpose="text")
            self.assertEqual(observed.source_window, repeat.source_window)
            self.assertEqual(observed.frame, repeat.frame)
