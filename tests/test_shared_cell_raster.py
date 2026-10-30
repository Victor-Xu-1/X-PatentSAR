"""Shared original source geometry, literal subviews, budgets and exact replay."""

import copy
import unittest
from unittest.mock import patch

import fitz
import numpy as np

from patent_sar_extractor.core.cell_raster import (
    cell_pixel_rect,
    cell_window_origin,
    render_cell_raster,
    valid_source_window,
)
from patent_sar_extractor.core.cell_rendering import CellRenderLimit
from patent_sar_extractor.core.plot_reference_pixels import pixel_reading, replay_pixels
from patent_sar_extractor.core.shared_cell_raster import (
    render_shared_cell_raster,
    shared_cell_view,
)

OWNER = [10.15, 20.25, 220.85, 140.95]
CHILD = [40.35, 35.55, 120.45, 100.65]


def original_page():
    document = fitz.open()
    page = document.new_page(width=260, height=200)
    page.draw_rect(fitz.Rect(55.2, 50.4, 100.6, 95.8), width=0.6)
    page.insert_text((60, 70), "37B", fontsize=9)
    source = document.tobytes()
    document.close()
    return fitz.open(stream=source, filetype="pdf")


class SharedCellRasterTests(unittest.TestCase):
    def test_subview_and_overlap_are_exact_original_bytes_without_another_render(self):
        with original_page() as document:
            page = document[0]
            before = document.tobytes(no_new_id=True)
            for dpi in (400, 600):
                source = render_cell_raster(page, OWNER, dpi)
                with patch(
                    "patent_sar_extractor.core.cell_raster.original_cell_pixmap",
                    side_effect=AssertionError("Subview selection may not rerender"),
                ):
                    view = shared_cell_view(source, OWNER, CHILD, dpi)
                self.assertTrue(
                    valid_source_window(
                        view.source_window, CHILD, dpi, view.frame["shape"]
                    )
                )
                x0, y0, x1, y1 = view.source_window["read_bounds"]
                np.testing.assert_array_equal(view.image, source.image[y0:y1, x0:x1])
                target = cell_pixel_rect(CHILD, dpi)
                self.assertEqual(
                    cell_window_origin(
                        view.source_window, CHILD, dpi, view.frame["shape"]
                    ),
                    [target.x0 * 72 / dpi, target.y0 * 72 / dpi],
                )
            self.assertEqual(document.tobytes(no_new_id=True), before)

    def test_original_replay_checks_parent_digest_even_outside_the_selected_cell(self):
        with original_page() as document:
            page = document[0]
            for dpi in (400, 600):
                view = render_shared_cell_raster(page, OWNER, CHILD, dpi)
                reading = pixel_reading(
                    view.image, dpi, source_window=view.source_window
                )
                np.testing.assert_array_equal(
                    replay_pixels(page, CHILD, reading), view.image
                )
                with fitz.open(stream=document.tobytes(), filetype="pdf") as changed:
                    changed[0].draw_rect(fitz.Rect(180, 110, 183, 113), fill=(0, 0, 0))
                    with self.assertRaises(ValueError):
                        replay_pixels(changed[0], CHILD, reading)

    def test_foreign_windows_and_unsupported_text_crops_never_qualify(self):
        with original_page() as document:
            view = render_shared_cell_raster(document[0], OWNER, CHILD, 400)
            for field in (
                "version",
                "purpose",
                "source_bbox",
                "source_shape",
                "read_bounds",
                "source_pixel_sha256",
                "frame_strips",
                "extra",
            ):
                window = copy.deepcopy(view.source_window)
                if field == "version":
                    window[field] = True
                elif field == "purpose":
                    window[field] = "text"
                elif field == "source_bbox":
                    window[field] = [50, 50, 220, 140]
                elif field in {"source_shape", "read_bounds"}:
                    window[field][0] += 1
                elif field == "source_pixel_sha256":
                    window[field] = "invalid"
                elif field == "frame_strips":
                    window[field] = [1, 1, 1, 1]
                else:
                    window[field] = True
                with self.subTest(field=field):
                    self.assertFalse(
                        valid_source_window(window, CHILD, 400, view.frame["shape"])
                    )
            for shape in ([True, 1, 3], None, "shape"):
                self.assertFalse(
                    valid_source_window(view.source_window, CHILD, 400, shape)
                )

    def test_oversized_parent_refuses_before_rendering_even_for_a_small_child(self):
        with fitz.open() as document:
            page = document.new_page(width=700, height=900)
            with patch(
                "patent_sar_extractor.core.cell_raster.original_cell_pixmap"
            ) as renderer:
                with self.assertRaises(CellRenderLimit):
                    render_shared_cell_raster(page, [0, 0, 700, 900], CHILD, 600)
                renderer.assert_not_called()

    def test_changed_child_or_parent_digest_cannot_be_replayed(self):
        with original_page() as document:
            page = document[0]
            view = render_shared_cell_raster(page, OWNER, CHILD, 400)
            reading = pixel_reading(view.image, 400, source_window=view.source_window)
            for field in ("pixel_sha256", "source_pixel_sha256"):
                changed = copy.deepcopy(reading)
                target = (
                    changed if field == "pixel_sha256" else changed["source_window"]
                )
                target[field] = "0" * 64
                with self.subTest(field=field), self.assertRaises(ValueError):
                    replay_pixels(page, CHILD, changed)
