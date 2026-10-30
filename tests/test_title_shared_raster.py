"""Generated scanned rulings keep one exact, bounded original pixel owner."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions
from patent_sar_extractor.core.title_ink_geometry import title_ink_rows
from patent_sar_extractor.core.title_ink_source import (
    observe_title_ink,
    replay_title_ink,
)
from patent_sar_extractor.core.title_shared_pixels import shared_title_bounds
from tests.test_caption_role_continuation import binding


def scanned_grid(source_dpi, offset, thickness, *, attached=False):
    """No private patent geometry, chemistry, reader or expected output values."""
    with fitz.open() as original:
        page = original.new_page(width=580, height=780)
        xs = [53.2 + offset + column * 148.4 for column in range(4)]
        ys = [97.3 + offset, 158.9 + offset, 189.7 + offset]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]), width=thickness)
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y), width=thickness)
        if attached:
            page.draw_line((140, ys[0] - 12), (140, ys[0] + 2), width=1)
        image = page.get_pixmap(dpi=source_dpi, alpha=False).tobytes("png")
    document = fitz.open()
    page = document.new_page(width=580, height=780)
    page.insert_image(page.rect, stream=image)
    return document


def ink_diagnostic(parent):
    ink = parent["title_context"].get("ink_source")
    if not isinstance(ink, dict):
        return {"ink_type": type(ink).__name__}
    rows = title_ink_rows(ink)
    return {
        "rows": rows,
        "version": ink["version"],
        "bounds": ink["bbox"],
        "window_refusal": ink["native_window"]["refusal"],
        "raster": ink["raster_source"] is not None,
        "closed": [r["pixels"] is not None for r in ink["ruling_sources"]],
    }


class SharedTitleRasterTests(unittest.TestCase):
    def observe(self, document):
        page = document[0]
        layout = source_layout(page)
        grids = detect_ruled_table_regions(page, dpi=240)
        self.assertEqual(len(grids), 1)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError("An empty original context needs no OCR"),
        ):
            scope = observe_caption_role(
                page, grids[0], grids, SourceTokens([], layout, tuple(page.rect))
            )
        return scope

    def test_complete_blank_scan_context_does_not_invent_crossing_title_ink(self):
        for dpi, offset, thickness in ((108, 0.53, 0.8), (216, 0.27, 0.65)):
            with (
                self.subTest(source_dpi=dpi),
                scanned_grid(dpi, offset, thickness) as document,
            ):
                scope = self.observe(document)
                self.assertEqual(scope["role"], "unknown")
                for source in scope["sources"]:
                    ink = source["title_context"]["ink_source"]
                    self.assertEqual(ink["version"], 6)
                    self.assertEqual(title_ink_rows(ink), ([], None))

    def test_real_unknown_stroke_attached_to_a_ruling_still_refuses(self):
        with scanned_grid(216, 0.27, 0.65, attached=True) as document:
            scope = self.observe(document)
            self.assertEqual(scope["role"], "unresolved")
            for source in scope["sources"]:
                ink = source["title_context"]["ink_source"]
                self.assertEqual(title_ink_rows(ink), ([], "crossing_title_ruling_ink"))

    def test_shared_frames_replay_and_cannot_be_downgraded_or_mixed(self):
        with scanned_grid(216, 0.27, 0.65) as document:
            scope = self.observe(document)
            ink = scope["sources"][0]["title_context"]["ink_source"]
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Pixel replay must not load OCR"),
            ):
                replay_title_ink(document[0], ink)
            downgraded = copy.deepcopy(ink)
            downgraded["version"] = 5
            self.assertIsNone(title_ink_rows(downgraded))
            mixed = copy.deepcopy(ink)
            mixed["ruling_sources"][0]["pixels"]["readings"][0]["source_window"][
                "source_pixel_sha256"
            ] = "0" * 64
            self.assertIsNone(title_ink_rows(mixed))
            document[0].draw_rect(fitz.Rect(400, 40, 403, 43), fill=(0, 0, 0))
            with self.assertRaises(ValueError):
                replay_title_ink(document[0], ink)

    def test_legacy_separate_clip_proof_keeps_its_original_read_only_recipe(self):
        with scanned_grid(216, 0.27, 0.65) as document:
            scope = self.observe(document)
            current = scope["sources"][0]["title_context"]["ink_source"]
            legacy = observe_title_ink(
                document[0], current["bbox"], current["context"], version=5
            )
            self.assertEqual(title_ink_rows(legacy), ([], "crossing_title_ruling_ink"))
            replay_title_ink(document[0], legacy)

    def test_one_paired_parent_per_capture_and_no_budget_or_outside_edge_escape(self):
        from patent_sar_extractor.core import title_shared_pixels

        with scanned_grid(216, 0.27, 0.65) as document:
            scope = self.observe(document)
            ink = scope["sources"][0]["title_context"]["ink_source"]
            renderer = title_shared_pixels.render_cell_raster
            with patch.object(
                title_shared_pixels, "render_cell_raster", wraps=renderer
            ) as capture:
                observe_title_ink(document[0], ink["bbox"], ink["context"])
            self.assertEqual(
                [call.args[2] for call in capture.call_args_list], [400, 600]
            )
        self.assertIsNone(
            shared_title_bounds([0, 0, 700, 500], [700, 900], [[20, 500, 680, 650]])
        )
        self.assertIsNone(
            shared_title_bounds([0, 150, 580, 180], [580, 780], [[20, 80, 560, 150]])
        )

    def test_scanned_below_diagram_catalogue_continues_without_repeating_a_header(self):
        with fitz.open() as document:
            structures, boxes = {}, {}
            for number, identifiers in enumerate(
                (("41A", "89B", "16C"), ("73D", "104E", "5F")), 1
            ):
                # The scanned boundary is separate from genuinely native
                # title/ID cells. Declaring native text over a full-page raster
                # would be an unproved native-layer claim, not this positive.
                strip = fitz.Rect(0, 95.57, 580, 99.57)
                with fitz.open() as original:
                    rule = original.new_page(width=580, height=4)
                    rule.draw_line((53.47, 2), (498.67, 2), width=0.65)
                    pixels = rule.get_pixmap(dpi=216).tobytes("png")
                page = document.new_page(width=580, height=780)
                page.insert_image(strip, stream=pixels, keep_proportion=False)
                xs = [53.47 + column * 148.4 for column in range(4)]
                for x in xs:
                    page.draw_line((x, 97.57), (x, 189.97), width=0.65)
                for y in (159.17, 189.97):
                    page.draw_line((xs[0], y), (xs[-1], y), width=0.65)
                if number == 1:
                    page.insert_text((53, 80), "Table 12. Compounds", fontsize=10)
                structures[number], boxes[number] = [], []
                for column, identifier in enumerate(identifiers):
                    left = 53.47 + column * 148.4
                    page.insert_text(
                        (left + 15, 179), f"Compound {identifier}", fontsize=9
                    )
                    box = [left + 25, 112, left + 85, 144]
                    page.draw_polyline(
                        [(box[0], box[3]), (box[0] + 30, box[1]), (box[2], box[3])]
                    )
                    structures[number].append(
                        {
                            "id": f"synthetic-{number}-{column}",
                            "page_no": number,
                            **dict(zip(("x0", "y0", "x1", "y1"), box, strict=True)),
                        }
                    )
                    boxes[number].append(box)
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Complete native captions need no OCR"),
            ) as reader_factory:
                result = bind_caption_grids(
                    document,
                    structures,
                    boxes,
                    [1, 2],
                    tokens_for_page=lambda page: SourceTokens(
                        source_layout(page).native, source_layout(page)
                    ),
                )
            self.assertEqual(
                [pair["label"] for pair in result.bindings],
                ["41A", "89B", "16C", "73D", "104E", "5F"],
                {
                    "issues": [
                        (issue.get("reason"), issue.get("page_no"))
                        for issue in result.issues
                    ],
                    "roles": [
                        (role.get("role"), role.get("table_key"))
                        for role in result.roles.values()
                    ],
                    "missing_reader_requests": reader_factory.call_count,
                    "ink_refusals": [
                        ink_diagnostic(source)
                        for role in result.roles.values()
                        for source in role["sources"]
                    ],
                },
            )
            self.assertEqual(result.issues, [])
            self.assertTrue(
                all(
                    valid_caption_binding_evidence(binding(pair))
                    for pair in result.bindings
                )
            )
