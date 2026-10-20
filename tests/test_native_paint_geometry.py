"""Original native ink envelopes must not become a font-box or OCR waiver."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.source_cell_tokens import crosses_cell
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.source_observations import (
    project_source_observation,
    source_cell_observation,
    source_observation_status,
)
from patent_sar_extractor.core.source_paint_visibility import visible_native_tokens
from tests.test_cell_boundary_ownership import BOUNDS, word_at_edge


class NativePaintGeometryTests(unittest.TestCase):
    def test_metric_descender_padding_cannot_invent_a_neighbour_cell_intersection(self):
        with word_at_edge("DC50 nM", "bottom", 2, 400, size=11) as (_, page):
            layout = source_layout(page)
            neighbour = [60, 150, 240, 200]
            self.assertTrue(any(t["bbox"][3] > neighbour[1] for t in layout.native))
            profile = source_cell_observation(
                SourceTokens(layout.native, layout), neighbour, native=True
            )
            self.assertEqual(profile["tokens"], [])
            self.assertEqual(profile["boundary_tokens"], [])
            self.assertEqual(source_observation_status(profile, neighbour, ""), "empty")

    def test_owned_metric_center_cannot_override_disjoint_original_paint(self):
        token = {
            "text": "x",
            "x": 110,
            "y": 160,
            "bbox": [100, 155, 120, 165],
            "source": "native",
            "confidence": 1.0,
            "native_paint": {"version": 1, "seqno": 0, "bbox": [100, 140, 120, 149]},
        }
        neighbour = [60, 150, 240, 200]
        self.assertTrue(crosses_cell([token], neighbour))

    def test_original_metric_boxes_are_preserved_while_padding_is_proved(self):
        with word_at_edge("DC50 nM", "top", 2, 400, size=11) as (_, page):
            words = page.get_text("words")
            layout = source_layout(page)
            self.assertEqual(
                [t["bbox"] for t in layout.native], [list(w[:4]) for w in words]
            )
            self.assertTrue(any(t["bbox"][1] < BOUNDS[1] - 1 for t in layout.native))
            self.assertFalse(crosses_cell(layout.native, BOUNDS))
            profile = source_cell_observation(
                SourceTokens(layout.native, layout), BOUNDS, native=True
            )
            saved = json.loads(json.dumps(profile))
            self.assertEqual(
                source_observation_status(saved, BOUNDS, "DC50 nM"), "qualified"
            )
            self.assertTrue(all("native_paint" in t for t in saved["tokens"]))
            child = project_source_observation(profile, BOUNDS)
            child["tokens"][0]["native_paint"]["bbox"][0] = 0
            self.assertNotEqual(
                child["tokens"][0]["native_paint"], profile["tokens"][0]["native_paint"]
            )
            profile["tokens"][0]["native_paint"]["bbox"][0] = 0
            self.assertNotEqual(
                profile["tokens"][0]["native_paint"], layout.native[0]["native_paint"]
            )

    def test_real_original_glyph_crossings_are_not_font_padding(self):
        for dpi in (400, 600):
            for edge in ("top", "bottom", "left", "right"):
                with (
                    self.subTest(dpi=dpi, edge=edge),
                    word_at_edge("IC50 nM", edge, -2, dpi, size=11) as (_, page),
                ):
                    layout = source_layout(page)
                    self.assertTrue(crosses_cell(layout.native, BOUNDS))

    def test_hidden_native_text_and_ambiguous_trace_membership_have_no_override(self):
        with fitz.open() as document:
            page = document.new_page(width=300, height=220)
            page.insert_text((90, 70), "DC50 nM", fontsize=11, render_mode=3)
            self.assertTrue(source_layout(page).native)
            self.assertTrue(
                all("native_paint" not in t for t in source_layout(page).native)
            )
        with word_at_edge("DC50 nM", "top", 2, 400, size=11) as (_, page):
            traces = page.get_texttrace()
            with patch.object(
                page, "get_texttrace", return_value=[*traces, *copy.deepcopy(traces)]
            ):
                self.assertTrue(
                    all("native_paint" not in t for t in source_layout(page).native)
                )
                self.assertTrue(crosses_cell(source_layout(page).native, BOUNDS))

    def test_stroked_and_artificial_bold_do_not_select_only_the_fill_envelope(self):
        for mode in (1, 2):
            with self.subTest(render_mode=mode), fitz.open() as document:
                page = document.new_page(width=300, height=220)
                page.insert_text(
                    (90, 70), "DC50 nM", fontsize=11, render_mode=mode, border_width=2
                )
                self.assertTrue(source_layout(page).native)
                self.assertTrue(
                    all("native_paint" not in t for t in source_layout(page).native)
                )

    def test_complete_paint_call_not_a_word_subset_must_fit_the_cell(self):
        with fitz.open() as document:
            page = document.new_page(width=500, height=220)
            page.insert_text(
                (90, 70), "DC50 nM                        outside", fontsize=11
            )
            layout = source_layout(page)
            self.assertTrue(any("native_paint" in t for t in layout.native))
            # The extra word is in the SAME original paint operation. Even a
            # known endpoint cannot choose the smaller successful word subset.
            self.assertTrue(crosses_cell(layout.native, [80, 60, 160, 160]))

    def test_rotation_uses_original_rendered_coordinates_without_global_font_flags(
        self,
    ):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), fitz.open() as document:
                page = document.new_page(width=300, height=220)
                page.insert_text((90, 70), "DC50 nM", fontsize=11)
                page.set_rotation(rotation)
                layout = source_layout(page)
                self.assertTrue(all("native_paint" in t for t in layout.native))
                for token in layout.native:
                    original = list(
                        page.get_bboxlog()[token["native_paint"]["seqno"]][1]
                    )
                    self.assertEqual(
                        token["native_paint"]["bbox"],
                        list(fitz.Rect(original) * page.rotation_matrix),
                    )

    def test_geometry_envelope_does_not_certify_paint_order_visibility(self):
        with word_at_edge("DC50 nM", "top", 2, 400, size=11) as (_, page):
            layout = source_layout(page)
            profile = source_cell_observation(
                SourceTokens(layout.native, layout), BOUNDS, native=True
            )
            self.assertTrue(visible_native_tokens(page, profile))
            page.draw_rect(
                fitz.Rect(90, 55, 160, 80), color=None, fill=(1, 1, 1), overlay=True
            )
            self.assertFalse(visible_native_tokens(page, profile))

    def test_invalid_or_raster_envelopes_cannot_be_admitted(self):
        with word_at_edge("DC50 nM", "top", 2, 400, size=11) as (_, page):
            layout = source_layout(page)
            profile = source_cell_observation(
                SourceTokens(layout.native, layout), BOUNDS, native=True
            )
            for change in ({"version": True}, {"seqno": -1}, {"bbox": [0, 0, 0, 0]}):
                changed = copy.deepcopy(profile)
                changed["tokens"][0]["native_paint"].update(change)
                self.assertEqual(
                    source_observation_status(changed, BOUNDS, "DC50 nM"), "invalid"
                )
            raster = copy.deepcopy(profile)
            raster["origin"] = "raster"
            raster["tokens"][0]["source"] = "raster"
            self.assertEqual(
                source_observation_status(raster, BOUNDS, "DC50 nM"), "invalid"
            )
