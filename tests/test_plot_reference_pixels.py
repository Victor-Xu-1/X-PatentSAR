"""Lossless bounded original masks, including corrupt/oversized zlib streams."""

import copy
import unittest
import zlib
from unittest.mock import patch

import fitz
import numpy as np

from patent_sar_extractor.core.plot_reference_pixels import (
    observe_pixels,
    retained_pixels,
)
from patent_sar_extractor.core.table_cells import cell_image


class OriginalPlotPixelTests(unittest.TestCase):
    def test_single_source_nomination_is_explicit_and_retains_the_same_pixel_contract(
        self,
    ):
        with fitz.open() as document:
            page = document.new_page(width=140, height=110)
            page.draw_line((20, 28), (100, 28), width=0.8)
            bounds = [12, 12, 112, 90]
            packet = observe_pixels(page, bounds, 1_000_000, resolutions=(400,))
            self.assertEqual([reading["dpi"] for reading in packet["readings"]], [400])
            self.assertIsNotNone(
                retained_pixels(packet["readings"][0], bounds, 400, 1_000_000)
            )
            for resolutions in ((True,), (600,), (400, 400), (400.0,), [400]):
                with (
                    self.subTest(resolutions=resolutions),
                    self.assertRaises((TypeError, ValueError)),
                ):
                    observe_pixels(page, bounds, 1_000_000, resolutions=resolutions)

    def test_the_caller_pixel_bound_is_enforced_before_render_allocation(self):
        with fitz.open() as document:
            page = document.new_page(width=140, height=110)
            with patch.object(
                page,
                "get_pixmap",
                side_effect=AssertionError("Over-budget pixels must not be allocated"),
            ) as render:
                self.assertIsNone(observe_pixels(page, [12, 12, 112, 90], 1000))
                render.assert_not_called()

    def test_original_masks_round_trip_without_changing_any_source_pixel(self):
        with fitz.open() as document:
            page = document.new_page(width=140, height=110)
            page.draw_line((20, 28), (100, 28), width=0.8)
            page.insert_text((25, 70), "0.001", fontsize=10)
            bounds = [12, 12, 112, 90]
            packet = observe_pixels(page, bounds, 1_000_000)
            for reading, dpi in zip(packet["readings"], (400, 600)):
                expected = np.min(cell_image(page, bounds, dpi), axis=2) < 180
                np.testing.assert_array_equal(
                    retained_pixels(reading, bounds, dpi, 1_000_000), expected
                )
                self.assertEqual(reading["mask_encoding"], "zlib-packbits-v1")
                self.assertLess(len(reading["mask_hex"]), expected.size // 8)

    @staticmethod
    def packet():
        shape = [9, 11, 3]
        bounds = [0, 0, 11 * 72 / 400 + 3, 9 * 72 / 400 + 2.4]
        reading = {
            "dpi": 400,
            "shape": shape,
            "pixel_sha256": "a" * 64,
            "mask_encoding": "zlib-packbits-v1",
            "mask_hex": zlib.compress(bytes(13)).hex(),
        }
        return reading, bounds

    def test_truncation_trailing_streams_bombs_and_padding_do_not_replay(self):
        reading, bounds = self.packet()
        self.assertIsNotNone(retained_pixels(reading, bounds, 400, 100))
        streams = (
            zlib.compress(bytes(13))[:-1],
            zlib.compress(bytes(13)) + b"foreign",
            zlib.compress(bytes(13)) + zlib.compress(bytes(13)),
            zlib.compress(bytes(100_000)),
            zlib.compress(bytes(12)),
            zlib.compress(bytes(12) + b"\x01"),
        )
        for index, stream in enumerate(streams):
            with self.subTest(index=index):
                changed = {**reading, "mask_hex": stream.hex()}
                self.assertIsNone(retained_pixels(changed, bounds, 400, 100))
        self.assertIsNone(retained_pixels(reading, bounds, 400, 98))

    def test_typed_format_and_geometry_are_not_legacy_or_flag_fallbacks(self):
        reading, bounds = self.packet()
        mutations = (
            {"dpi": True},
            {"dpi": 400.0},
            {"shape": [True, 11, 3]},
            {"shape": [9, 12, 3]},
            {"shape": [9, 11, 4]},
            {"mask_encoding": "raw"},
            {"mask_hex": "1"},
            {"mask_hex": "xx"},
            {"pixel_sha256": "bad"},
            {"accepted": True},
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                changed = {**copy.deepcopy(reading), **mutation}
                self.assertIsNone(retained_pixels(changed, bounds, 400, 100))
        legacy = copy.deepcopy(reading)
        legacy.pop("mask_encoding")
        self.assertIsNone(retained_pixels(legacy, bounds, 400, 100))


if __name__ == "__main__":
    unittest.main()
