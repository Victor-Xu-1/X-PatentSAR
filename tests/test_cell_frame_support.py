"""Paired original geometry is bounded evidence, never a text/model vote."""

import copy
import hashlib
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.cell_frame_proof import (
    original_cell_frame_matches,
    valid_cell_frame,
)
from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.cell_raster import (
    original_reading_image,
    render_cell_raster,
    valid_source_window,
)
from patent_sar_extractor.core.cell_rendering import (
    historical_cell_image,
    original_cell_pixmap,
)
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions
from tests.test_caption_role_raster import raster_catalog


def dense_cell():
    document, _, _ = raster_catalog(
        prefixed=True, labels=("53Q", "0061"), label_height=14, label_fontname="hebo"
    )
    grid = detect_ruled_table_regions(document[0], dpi=240)[0]
    return document, [grid["xs"][0], grid["ys"][0], grid["xs"][1], grid["ys"][1]]


class CellFrameSupportTests(unittest.TestCase):
    def test_legacy_inset_can_be_viewed_but_not_admitted_as_current_complete_source(
        self,
    ):
        with fitz.open() as document:
            page = document.new_page(width=180, height=100)
            page.insert_text((30, 50), "DC50 nM", fontsize=9)
            bounds = [20, 20, 160, 80]
            image = historical_cell_image(page, bounds, 400)
            observed = observe_cell(
                image,
                "header",
                400,
                lambda *_a, **_k: ([["DC50 nM", 0.99]], None),
                lambda t, _k: t,
            ).evidence(400, bounds)
            observed["source_frame"] = {
                "dpi": 400,
                "shape": list(image.shape),
                "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
            }
            self.assertTrue(
                valid_cell_frame(observed["source_frame"], observed, bounds, 400)
            )
            self.assertEqual(
                original_reading_image(page, bounds, 400, observed).tobytes(),
                image.tobytes(),
            )
            self.assertFalse(original_cell_frame_matches(observed, page))

    def test_only_same_original_geometric_frames_can_separate_dense_ruling(self):
        document, bounds = dense_cell()
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Geometry cannot load OCR"),
            ),
        ):
            observed = render_cell_raster(document[0], bounds, 400, purpose="text")
            raw = render_cell_raster(document[0], bounds, 400)
            high = render_cell_raster(document[0], bounds, 600, purpose="text")
            self.assertIn("support", observed.source_window)
            self.assertEqual(
                observed.source_window["source_pixel_sha256"], raw.frame["pixel_sha256"]
            )
            self.assertEqual(
                observed.source_window["support"],
                {"frame": high.frame, "window": high.source_window},
            )
            self.assertNotIn("support", raw.source_window)
            self.assertNotIn("support", high.source_window)
            self.assertTrue(
                valid_source_window(
                    observed.source_window, bounds, 400, observed.frame["shape"]
                )
            )
            reading = {
                "source_window": observed.source_window,
                "source_frame": observed.frame,
            }
            self.assertEqual(
                original_reading_image(document[0], bounds, 400, reading).tobytes(),
                observed.image.tobytes(),
            )

    def test_support_is_not_unbounded_or_foreign_metadata_fallback(self):
        document, bounds = dense_cell()
        with document:
            raster = render_cell_raster(document[0], bounds, 400, purpose="text")
            original = {
                "source_window": raster.source_window,
                "source_frame": raster.frame,
            }
            for mode in ("digest", "omitted", "recursive", "wrong_dpi", "wrong_shape"):
                changed = copy.deepcopy(original)
                support = changed["source_window"]["support"]
                if mode == "digest":
                    support["window"]["source_pixel_sha256"] = "0" * 64
                elif mode == "omitted":
                    del changed["source_window"]["support"]
                elif mode == "recursive":
                    support["window"]["support"] = copy.deepcopy(support)
                elif mode == "wrong_dpi":
                    support["frame"]["dpi"] = 400
                else:
                    support["frame"]["shape"][0] += 1
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    original_reading_image(document[0], bounds, 400, changed)
            with fitz.open(stream=document.tobytes(), filetype="pdf") as other:
                other[0].insert_text(
                    (bounds[0] + 10, bounds[1] + 9), "Added", fontsize=5
                )
                with self.assertRaises(ValueError):
                    original_reading_image(other[0], bounds, 400, original)

    def test_support_allocation_obeys_the_callers_original_pixel_bound(self):
        document, bounds = dense_cell()
        with document:
            raw = render_cell_raster(document[0], bounds, 400)
            maximum = raw.image.shape[0] * raw.image.shape[1]
            with patch(
                "patent_sar_extractor.core.cell_raster.original_cell_pixmap",
                wraps=original_cell_pixmap,
            ) as render:
                observed = render_cell_raster(
                    document[0], bounds, 400, maximum_pixels=maximum, purpose="text"
                )
                self.assertEqual(render.call_count, 1)
            self.assertNotIn("support", observed.source_window)
            self.assertEqual(observed.source_window["support_limit"], maximum)
            self.assertEqual(observed.image.tobytes(), raw.image.tobytes())
            reading = {
                "source_window": observed.source_window,
                "source_frame": observed.frame,
            }
            self.assertEqual(
                original_reading_image(document[0], bounds, 400, reading).tobytes(),
                observed.image.tobytes(),
                "Readback must preserve the producer's explicit source-pixel budget",
            )
            for limit in (True, 0, 8_000_000):
                changed = copy.deepcopy(reading)
                changed["source_window"]["support_limit"] = limit
                with self.subTest(limit=limit):
                    self.assertFalse(
                        valid_source_window(
                            changed["source_window"],
                            bounds,
                            400,
                            observed.frame["shape"],
                        )
                    )

    def test_real_touching_mark_cannot_be_erased_by_a_higher_resolution(self):
        document, bounds = dense_cell()
        with document:
            page = document[0]
            page.draw_line(
                (bounds[0] + 10, bounds[1]), (bounds[0] + 10, bounds[1] + 7), width=0.4
            )
            observed = render_cell_raster(page, bounds, 400, purpose="text")
            raw = render_cell_raster(page, bounds, 400)
            self.assertNotIn("support", observed.source_window)
            self.assertIsNone(observed.source_window["frame_strips"])
            self.assertEqual(observed.image.tobytes(), raw.image.tobytes())
