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


def scan_like(image):
    # Controlled scan-like blur/resampling; no OCR or recognition engine.
    image = image.filter(ImageFilter.GaussianBlur(0.45))
    return image.resize((image.width * 2, image.height * 2)).resize(image.size)


def straight_serif_branch(length, slope):
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    # A small angular glyph/branch adjoining one entirely straight tilted leg.
    draw.line([(40, 68), (40, 62), (43, 62)], fill="black", width=1)
    draw.line([(40, 65), (42, 65)], fill="black", width=1)
    draw.line([(43, 62), (43 + length * slope, 62 - length)], fill="black", width=1)
    return image


def wave_drawing(layout, *, amplitude=3, period=12, length=84, noise=False):
    image = Image.new("RGB", (230, 150), "white")
    draw = ImageDraw.Draw(image)
    x0, y0 = 70, 60
    points = [
        (x0 + i, y0 + amplitude * math.sin(2 * math.pi * i / period))
        for i in range(length + 1)
    ]
    if layout == "attached":
        draw.line(
            [(35, 40), (70, 40), (70, 90), (35, 90), (35, 40)], fill="black", width=2
        )
        draw.line(
            [(x0 + length, y0), (x0 + length + min(36, length / 2), y0)],
            fill="black",
            width=2,
        )
    elif layout == "cycle":
        draw.line(
            [(x0, y0), (x0, 105), (x0 + length, 105), (x0 + length, y0)],
            fill="black",
            width=2,
        )
    draw.line(points, fill="black", width=2)
    if noise:
        image = scan_like(image)
    return image


class BondStrokeGeometryTests(unittest.TestCase):
    def test_short_straight_serif_branches_are_not_supported_waves(self):
        for length, slope in ((12, 0.3), (15, 0.2), (18, 0.3)):
            for angle in (0, 15, 30, 45, 60, 75, 90, 135):
                for scan in (False, True):
                    with self.subTest(
                        length=length, slope=slope, angle=angle, scan=scan
                    ):
                        image = straight_serif_branch(length, slope).rotate(
                            angle,
                            resample=(
                                Image.Resampling.BICUBIC
                                if scan
                                else Image.Resampling.NEAREST
                            ),
                            expand=True,
                            fillcolor="white",
                        )
                        if scan:
                            image = scan_like(image)
                        self.assertEqual(
                            observe_stereo_symbols(png(image))["unknown_bond_boxes"], []
                        )

    def test_two_round_bends_cannot_compensate_for_a_straight_middle_leg(self):
        x = np.arange(0, 24.25, 0.25)
        y = 3 * np.sin(x * math.pi / 6)
        straight = (x >= 9) & (x <= 15)
        y[straight] = -3 + (x[straight] - 9)
        self.assertFalse(is_periodic_wave(np.column_stack((x, y))))
        self.assertTrue(
            is_periodic_wave(np.column_stack((x, 3 * np.sin(x * math.pi / 6))))
        )

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

    def test_small_waves_have_independent_bends_even_in_connected_layouts(self):
        for length, amplitude, period in ((30, 2, 10), (36, 3, 12)):
            for layout in ("isolated", "attached", "cycle"):
                for angle in (0, 30, 60, 90, 135):
                    for noise in (False, True):
                        with self.subTest(
                            length=length, layout=layout, angle=angle, noise=noise
                        ):
                            image = wave_drawing(
                                layout,
                                amplitude=amplitude,
                                period=period,
                                length=length,
                                noise=noise,
                            ).rotate(
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
