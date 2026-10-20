"""Source-pixel conservation before wiring the shared PDF frame consumers."""

import unittest

import numpy as np

from patent_sar_extractor.core.cell_window import CellWindow, select_cell_window


def framed():
    image = np.full((90, 180, 3), 255, dtype=np.uint8)
    image[3:87, 3:5] = 0
    image[3:87, 175:177] = 0
    image[3:5, 3:177] = 0
    image[85:87, 3:177] = 0
    image[25:40, 20:23] = 0
    image[38:41, 20:40] = 0
    return image


class CellWindowTests(unittest.TestCase):
    def test_unruled_blank_and_edge_ink_keep_the_complete_source(self):
        for position in (None, (0, 0), (89, 179), (0, 90), (45, 0)):
            image = np.full((90, 180, 3), 255, dtype=np.uint8)
            if position is not None:
                image[position] = [254, 255, 255]
            with self.subTest(position=position):
                selected = select_cell_window(image, 400)
                self.assertEqual(selected, CellWindow((0, 0, 180, 90)))
                np.testing.assert_array_equal(selected.view(image), image)

    def test_only_an_isolated_complete_frame_can_be_excluded(self):
        image = framed()
        for dpi in (150, 400, 450, 600):
            with self.subTest(dpi=dpi):
                selected = select_cell_window(image, dpi, allow_text_frame=True)
                self.assertEqual(selected, CellWindow((5, 5, 175, 85), (2, 2, 2, 2)))
                np.testing.assert_array_equal(selected.view(image), image[5:85, 5:175])
                self.assertTrue(np.shares_memory(selected.view(image), image))

    def test_a_single_white_corner_pixel_does_not_hide_the_separate_complete_frame(
        self,
    ):
        image = framed()
        image[3, 3] = 255
        selected = select_cell_window(image, 400, allow_text_frame=True)
        self.assertEqual(selected, CellWindow((5, 5, 175, 85), (2, 2, 2, 2)))
        np.testing.assert_array_equal(selected.view(image), image[5:85, 5:175])

    def test_outward_dark_or_faint_marks_cannot_be_discarded_with_a_frame(self):
        for color in ([0, 0, 0], [254, 255, 255]):
            image = framed()
            image[2, 80] = color
            with self.subTest(color=color):
                selected = select_cell_window(image, 400, allow_text_frame=True)
                self.assertEqual(selected.bounds, (0, 0, 180, 90))
                np.testing.assert_array_equal(selected.view(image), image)

    def test_literal_dashes_keep_the_existing_rule_gap_limit_without_filling(self):
        for gap, accepted in ((4, True), (24, False)):
            image = framed()
            for start in range(8, 170, 4 + gap):
                image[3:5, start : start + gap] = 255
                image[85:87, start : start + gap] = 255
            for start in range(8, 80, 4 + gap):
                image[start : start + gap, 3:5] = 255
                image[start : start + gap, 175:177] = 255
            with self.subTest(gap=gap):
                selected = select_cell_window(image, 400, allow_text_frame=True)
                self.assertEqual(selected.frame_strips is not None, accepted)
                if accepted:
                    np.testing.assert_array_equal(
                        selected.view(image), image[5:85, 5:175]
                    )

    def test_open_frame_and_partial_edge_lines_cannot_remove_any_source(self):
        for mutation in ("gap", "no_left", "no_top", "crossing"):
            image = framed()
            if mutation == "gap":
                image[3:5, 80:104] = 255  # Above the shared 1.5pt gap policy.
            elif mutation == "no_left":
                image[5:85, 3:5] = 255
            elif mutation == "no_top":
                image[3:5, 5:175] = 255
            else:
                image[4:26, 21:23] = 0
            with self.subTest(mutation=mutation):
                self.assertEqual(
                    select_cell_window(image, 400, allow_text_frame=True).bounds,
                    (0, 0, 180, 90),
                )

    def test_touching_dark_or_faint_ink_is_not_erased_with_the_frame(self):
        for color in ([0, 0, 0], [254, 255, 255]):
            for row, column in ((5, 50), (84, 50), (40, 5), (40, 174), (5, 5)):
                image = framed()
                image[row, column] = color
                with self.subTest(color=color, position=(row, column)):
                    self.assertIsNone(
                        select_cell_window(
                            image, 400, allow_text_frame=True
                        ).frame_strips
                    )

    def test_opaque_thick_or_uneven_blocks_do_not_become_frames(self):
        solid = np.zeros((90, 180, 3), dtype=np.uint8)
        thick = np.zeros((90, 180, 3), dtype=np.uint8)
        thick[25:65, 25:155] = 255
        uneven = framed()
        uneven[5:10, 30:40] = 0
        for image in (solid, thick, uneven):
            with self.subTest(shape=image.shape):
                self.assertEqual(
                    select_cell_window(image, 400, allow_text_frame=True).bounds,
                    (0, 0, 180, 90),
                )

    def test_nested_frame_is_retained_as_inner_content_not_recursively_removed(self):
        image = framed()
        image[15, 10:160] = 0
        image[70, 10:160] = 0
        image[15:71, 10] = 0
        image[15:71, 159] = 0
        selected = select_cell_window(image, 400, allow_text_frame=True)
        self.assertEqual(selected.bounds, (5, 5, 175, 85))
        self.assertEqual(
            int(np.count_nonzero(selected.view(image)[10, :, 0] == 0)), 150
        )

    def test_unknown_or_nontext_rectangular_diagrams_never_lose_their_ring(self):
        image = framed()
        selected = select_cell_window(image, 400)
        self.assertEqual(selected.bounds, (0, 0, 180, 90))
        np.testing.assert_array_equal(selected.view(image), image)

    def test_bare_closed_rectangle_cannot_be_promoted_to_an_empty_text_cell(self):
        image = framed()
        image[5:85, 5:175] = 255
        selected = select_cell_window(image, 400, allow_text_frame=True)
        self.assertEqual(selected.bounds, (0, 0, 180, 90))
        np.testing.assert_array_equal(selected.view(image), image)

    def test_malformed_or_over_budget_images_refuse_without_coercion(self):
        for image, dpi in (
            (None, 400),
            (np.zeros((5, 5), dtype=np.uint8), 400),
            (np.zeros((5, 5, 4), dtype=np.uint8), 400),
            (np.zeros((5, 5, 3), dtype=np.float32), 400),
            (np.zeros((0, 5, 3), dtype=np.uint8), 400),
            (np.zeros((2001, 4000, 3), dtype=np.uint8), 400),
            (framed(), True),
            (framed(), 0),
            (framed(), 1201),
        ):
            with self.subTest(dpi=dpi), self.assertRaises(ValueError):
                select_cell_window(image, dpi)
