"""Synthetic straight-ring and true-wave controls, with no private patent data."""

from __future__ import annotations

import io
import math
import unittest
from itertools import pairwise

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from patent_sar_extractor.core.ocsr.bond_strokes import is_periodic_wave
from patent_sar_extractor.core.ocsr.stereo_evidence import observe_stereo_symbols


def png(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def ring_branch_image():
    image = Image.new("RGB", (160, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(60, 55), (80, 65), (70, 85), (50, 75), (60, 55)], fill="black", width=2)
    draw.line([(60, 55), (65, 37)], fill="black", width=2)
    draw.line([(70, 85), (65, 103)], fill="black", width=2)
    draw.text((60, 105), "F", fill="black")
    return image


def wave_drawing(layout, *, amplitude=3, period=12, noise=False):
    image = Image.new("RGB", (230, 150), "white")
    draw = ImageDraw.Draw(image)
    x0, y0, length = 70, 60, 84
    points = [
        (x0 + i, y0 + amplitude * math.sin(2 * math.pi * i / period))
        for i in range(length + 1)
    ]
    if layout == "attached":
        draw.line(
            [(35, 40), (70, 40), (70, 90), (35, 90), (35, 40)], fill="black", width=2
        )
        draw.line([(x0 + length, y0), (190, y0)], fill="black", width=2)
    elif layout == "cycle":
        draw.line(
            [(x0, y0), (x0, 105), (x0 + length, 105), (x0 + length, y0)],
            fill="black",
            width=2,
        )
    draw.line(points, fill="black", width=2)
    if noise:
        # Controlled scan-like blur/low contrast; no OCR or recognition engine.
        image = image.filter(ImageFilter.GaussianBlur(0.45))
        image = image.resize((460, 300)).resize((230, 150))
    return image


class BondStrokeGeometryTests(unittest.TestCase):
    def test_normal_rotated_ring_and_f_branch_never_become_unknown_bond(self):
        image = ring_branch_image()
        for angle in (0, 15, 30, 45, 60, 75, 90, 135):
            for resampling in (Image.Resampling.NEAREST, Image.Resampling.BICUBIC):
                with self.subTest(angle=angle, resampling=resampling):
                    rotated = image.rotate(
                        angle, resample=resampling, expand=True, fillcolor="white"
                    )
                    self.assertEqual(
                        observe_stereo_symbols(png(rotated))["unknown_bond_boxes"], []
                    )

    def test_polygon_corner_chain_is_not_a_smooth_periodic_stroke(self):
        # A regular carbon zigzag has repeated extrema but straight half-periods.
        points = np.array(
            [
                (x, 70 + (4 if index % 2 else -4))
                for index, x in enumerate(range(20, 101, 10))
            ],
            dtype=float,
        )
        dense = np.concatenate(
            [
                np.linspace(left, right, 21, endpoint=False)
                for left, right in pairwise(points)
            ]
        )
        self.assertFalse(is_periodic_wave(dense))

    def test_closed_regular_polygons_are_not_masked_or_reported_as_waves(self):
        for sides in (3, 4, 5, 6, 8):
            for angle in (0, 15, 30, 75):
                with self.subTest(sides=sides, angle=angle):
                    image = Image.new("RGB", (160, 160), "white")
                    ImageDraw.Draw(image).regular_polygon(
                        (80, 80, 25), sides, rotation=angle, outline="black", width=2
                    )
                    self.assertEqual(
                        observe_stereo_symbols(png(image))["unknown_bond_boxes"], []
                    )

    def test_tilted_straight_leg_with_raster_staircases_is_not_periodic_wave(self):
        image = Image.new("RGB", (180, 140), "white")
        ImageDraw.Draw(image).line([(40, 105), (100, 65)], fill="black", width=2)
        for angle in (15, 30, 60, 75):
            with self.subTest(angle=angle):
                self.assertEqual(
                    observe_stereo_symbols(
                        png(image.rotate(angle, expand=True, fillcolor="white"))
                    )["unknown_bond_boxes"],
                    [],
                )

    def test_true_waves_attached_to_rings_and_inside_cycles_remain_detected(self):
        for layout in ("isolated", "attached", "cycle"):
            for angle in (0, 30, 60, 90, 135):
                for noise in (False, True):
                    with self.subTest(layout=layout, angle=angle, noise=noise):
                        image = wave_drawing(layout, noise=noise).rotate(
                            angle,
                            resample=Image.Resampling.BICUBIC,
                            expand=True,
                            fillcolor="white",
                        )
                        self.assertTrue(
                            observe_stereo_symbols(png(image))["unknown_bond_boxes"]
                        )

    def test_smooth_wave_is_not_erased_by_connected_straight_legs(self):
        wave = np.column_stack(
            (
                np.arange(20, 104.5, 0.5),
                70 + 3 * np.sin(np.arange(0, 84.5, 0.5) * math.pi / 6),
            )
        )
        left = np.column_stack((np.arange(0, 20, 0.5), np.full(40, 70)))
        right = np.column_stack((np.arange(104.5, 124.5, 0.5), np.full(40, 70)))
        points = np.vstack((left, wave, right))
        self.assertTrue(is_periodic_wave(points))


if __name__ == "__main__":
    unittest.main()
