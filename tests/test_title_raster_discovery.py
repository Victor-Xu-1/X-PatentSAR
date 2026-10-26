"""Complete raster catalogue context without any recognized title-word locator."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_observation import (
    observe_caption_role,
    owns_caption_frame,
)
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.structure_catalogs import catalog_for_caption_scope
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions
from patent_sar_extractor.core.title_ink_geometry import title_ink_rows
from patent_sar_extractor.core.title_original_replay import replay_source_title
from patent_sar_extractor.core.title_source_inventory import title_source_cells
from tests import test_catalogue_title_source as title_fixtures
from tests.test_caption_source_roles import catalog


def raster_catalogue(title, *, entire_page=True, title_y=85, width=None, rows=()):
    original, structures, boxes = catalog(None, prefixed=True)
    page = original[0]
    if width is not None:
        page.set_mediabox(fitz.Rect(0, 0, width, page.rect.height))
    if title and entire_page:
        page.insert_text((50, title_y), title, fontsize=10)
    for y, text, fontsize in rows:
        page.insert_text((50, y), text, fontsize=fontsize)
    if not entire_page:
        # A genuine image-only heading above a native original grid/ID region.
        window = fitz.Rect(0, 0, page.rect.width, 96)
        with fitz.open() as lettering:
            heading = lettering.new_page(width=window.width, height=window.height)
            heading.insert_text((50, title_y), title, fontsize=10)
            pixels = heading.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        page.insert_image(window, stream=pixels.tobytes("png"))
        return original, structures, boxes
    pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    width, height = page.rect.width, page.rect.height
    original.close()
    raster = fitz.open()
    page = raster.new_page(width=width, height=height)
    page.insert_image(page.rect, stream=pixels.tobytes("png"))
    return raster, structures, boxes


class TitleRasterDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.factory = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError("No native model in controlled regressions"),
            )
        )
        self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            )
        )

    def tearDown(self):
        self.assertEqual(self.factory.call_count, 0)

    def observe(self, document, title, *, reader=None, engines=None):
        page = document[0]
        layout = source_layout(page)
        tokens = SourceTokens([], layout, tuple(page.rect))
        grids = detect_ruled_table_regions(page, dpi=240)
        self.assertEqual(len(grids), 1)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=engines,
            return_value=(
                "rapidocr",
                reader or title_fixtures.CatalogueTitleSourceTests.engine(title),
            ),
        ) as factory:
            scope = observe_caption_role(page, grids[0], grids, tokens)
        return grids, tokens, scope, factory.call_count

    def test_scan_without_title_words_recovers_original_nonfinal_role(self):
        title = "Table 62. Intermediate compounds"
        document, _structures, _boxes = raster_catalogue(title)
        with document:
            _grids, _tokens, scope, calls = self.observe(document, title)
            self.assertEqual(scope["observations"], [])
            self.assertEqual(
                (scope["role"], scope["table_key"]), ("nonfinal", "TABLE62")
            )
            self.assertEqual(calls, 1)
            saved = json.loads(json.dumps(scope))
            self.assertEqual(
                caption_role_status(saved, 1, saved["table_bbox"]), "nonfinal"
            )

    def test_scan_compound_role_reaches_the_existing_catalogue_consumer(self):
        title = "Table C. Selected compounds"
        document, _structures, _boxes = raster_catalogue(title)
        with document:
            _grids, _tokens, scope, _calls = self.observe(document, title)
            self.assertEqual(scope["role"], "compound")
            catalogue = catalog_for_caption_scope(scope)
            self.assertEqual(catalogue.identifier, "Table C")
            self.assertTrue(catalogue.selected_subset)

    def test_image_title_above_native_ids_uses_the_same_formal_binding_path(self):
        title = "Table 73. Compounds"
        document, structures, boxes = raster_catalogue(title, entire_page=False)
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                return_value=(
                    "rapidocr",
                    title_fixtures.CatalogueTitleSourceTests.engine(title),
                ),
            ),
        ):
            result = bind_caption_grids(
                document,
                structures,
                boxes,
                [1],
                tokens_for_page=lambda page: SourceTokens(
                    source_layout(page).native, source_layout(page)
                ),
            )
            self.assertEqual(
                [b["label"] for b in result.bindings], ["I-004A", "I-009B"]
            )
            self.assertEqual(result.issues, [])

    def test_mixed_scan_role_does_not_publish_or_silently_exclude(self):
        title = "Table 19. Compounds and intermediates"
        document, _structures, _boxes = raster_catalogue(title)
        with document:
            _grids, _tokens, scope, _calls = self.observe(document, title)
            self.assertIn(scope["role"], {"mixed", "conflict", "unresolved"})

    def test_raster_proof_requires_every_original_row_and_pixel_record(self):
        title = "Table 62. Intermediate compounds"
        document, _structures, _boxes = raster_catalogue(title)
        with document:
            _grids, _tokens, scope, _calls = self.observe(document, title)
            self.assertEqual(scope["role"], "nonfinal")
            for changed_field in ("original_titles", "raster_source"):
                changed = copy.deepcopy(scope)
                for parent in changed["sources"]:
                    if changed_field == "original_titles":
                        parent[changed_field].clear()
                    else:
                        parent["title_context"]["ink_source"].pop(changed_field, None)
                self.assertIsNone(
                    caption_role_status(changed, 1, changed["table_bbox"])
                )

    def test_original_pixels_are_replayed_without_acquiring_a_reader(self):
        title = "Table 62. Intermediate compounds"
        document, _structures, boxes = raster_catalogue(title)
        with document:
            grids, tokens, scope, _calls = self.observe(document, title)
            self.assertEqual(scope["role"], "nonfinal")
            records = [r for p in scope["sources"] for r in p["original_titles"]]
            self.assertEqual(len(records), 1)
            cells = list(
                title_source_cells(
                    {
                        "source_sections": [
                            {
                                "role": "nonfinal_caption_catalog",
                                "caption_role": scope,
                            }
                        ],
                    }
                )
            )
            self.assertEqual(original_role_source_errors(document, cells), [])
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Source replay must not repeat OCR"),
            ):
                replay_source_title(document[0], records[0])
                self.assertTrue(
                    owns_caption_frame(
                        document[0],
                        grids[0],
                        grids,
                        tokens,
                        boxes[1],
                        original_role=scope,
                    )
                )
                document[0].draw_rect(fitz.Rect(420, 40, 424, 45), fill=(0, 0, 0))
                with self.assertRaises(ValueError):
                    replay_source_title(document[0], records[0])
                self.assertTrue(original_role_source_errors(document, cells))

    def test_crossing_context_ink_refuses_before_any_text_reader(self):
        document, _structures, _boxes = raster_catalogue("Table 62. Compounds")
        with document:
            document[0].draw_rect(fitz.Rect(420, 90, 424, 110), fill=(0, 0, 0))
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Crossing ink must refuse before OCR"),
            ):
                layout = source_layout(document[0])
                tokens = SourceTokens([], layout, tuple(document[0].rect))
                grids = detect_ruled_table_regions(document[0], dpi=240)
                scope = observe_caption_role(document[0], grids[0], grids, tokens)
            self.assertEqual(scope["role"], "unresolved")

    def test_oversized_context_refuses_before_text_or_pixel_allocation(self):
        document, _structures, _boxes = raster_catalogue(
            "Table 62. Compounds", width=3000
        )
        with document:
            with patch(
                "patent_sar_extractor.core.title_raster_source.observe_pixels",
                side_effect=AssertionError("Source pixel budget precedes rendering"),
            ):
                _grids, _tokens, scope, calls = self.observe(document, "")
            self.assertEqual(calls, 0)
            self.assertEqual(scope["role"], "unresolved")
            ink = scope["sources"][0]["title_context"]["ink_source"]
            self.assertEqual(title_ink_rows(ink)[1], "title_raster_pixel_budget")

    def test_failed_ruling_budget_does_not_render_an_unusable_raster_context(self):
        document, _structures, _boxes = raster_catalogue("Table 62. Compounds")
        with (
            document,
            patch("patent_sar_extractor.core.title_ink_geometry.MAX_CELL_PIXELS", 1),
            patch(
                "patent_sar_extractor.core.title_raster_source.observe_pixels",
                side_effect=AssertionError(
                    "A prior source-budget refusal needs no pixels"
                ),
            ),
        ):
            _grids, _tokens, scope, calls = self.observe(document, "")
            self.assertEqual(calls, 0)
            ink = scope["sources"][0]["title_context"]["ink_source"]
            self.assertIsNone(ink["raster_source"])
            self.assertEqual(title_ink_rows(ink)[1], "title_ruling_budget")

    def test_wrapped_scan_title_keeps_its_table_key_and_all_original_rows(self):
        first, second = "Table 26. Intermediate", "compounds"
        document, _structures, _boxes = raster_catalogue(
            first, title_y=70, rows=[(85, second, 10)]
        )
        engines = [
            ("rapidocr", title_fixtures.CatalogueTitleSourceTests.engine(text))
            for text in (first, second)
        ]
        with document:
            _grids, _tokens, scope, calls = self.observe(document, "", engines=engines)
            self.assertEqual(
                (scope["role"], scope["table_key"]), ("nonfinal", "TABLE26")
            )
            self.assertEqual(calls, 2)
            records = [r for p in scope["sources"] for r in p["original_titles"]]
            self.assertEqual(len(records), 2)
            changed = copy.deepcopy(scope)
            next(p for p in changed["sources"] if p["original_titles"])[
                "original_titles"
            ].pop()
            self.assertIsNone(caption_role_status(changed, 1, changed["table_bbox"]))

    def test_excess_original_rows_cannot_choose_the_last_readable_title(self):
        document, _structures, _boxes = raster_catalogue(
            None, rows=[(8 + 9 * i, f"Original row {i}", 5) for i in range(9)]
        )
        with document:
            _grids, _tokens, scope, calls = self.observe(
                document, "Table 62. Compounds"
            )
            self.assertEqual(calls, 0)
            self.assertEqual(scope["role"], "unresolved")
            ink = scope["sources"][0]["title_context"]["ink_source"]
            self.assertEqual(title_ink_rows(ink)[1], "title_row_budget")

    def test_paired_role_disagreement_and_weak_readings_remain_unresolved(self):
        for responses in (
            [("Table 62. Compounds", 0.99), ("Table 62. Intermediates", 0.99)],
            [("Table 62. Compounds", 0.2)] * 4,
        ):
            with self.subTest(responses=responses):
                document, _structures, _boxes = raster_catalogue("Table 62. Compounds")
                with document:
                    observations = iter(responses)

                    def controlled(
                        image, *, use_det, use_cls, observations=observations
                    ):
                        if use_det:
                            return [], None
                        text, confidence = next(observations)
                        return [[text, confidence]], None

                    _grids, _tokens, scope, _calls = self.observe(
                        document, "", reader=controlled
                    )
                    self.assertEqual(scope["role"], "unresolved")

    def test_unknown_ink_attached_to_a_rule_is_not_erased_to_make_text_readable(self):
        document, _structures, _boxes = raster_catalogue("Table 62. Compounds")
        with document:
            document[0].draw_line((150, 90), (150, 102), width=1)
            _grids, _tokens, scope, calls = self.observe(
                document, "Table 62. Compounds"
            )
            self.assertEqual(calls, 0)
            self.assertEqual(scope["role"], "unresolved")

    def test_unnumbered_scan_category_never_invents_a_table_identifier(self):
        title = "Intermediate compounds"
        document, _structures, _boxes = raster_catalogue(title)
        with document:
            _grids, _tokens, scope, _calls = self.observe(document, title)
            self.assertEqual((scope["role"], scope["table_key"]), ("nonfinal", ""))

    def test_unruled_columns_use_the_same_complete_scan_title(self):
        import hashlib

        from patent_sar_extractor.core.logical_column_partitions import (
            nominate_unruled_headers,
        )
        from patent_sar_extractor.core.unruled_structure_headers import (
            observe_unruled_header,
            unruled_header_roles,
        )

        title = "Table H. Intermediate compounds"
        with fitz.open() as document, fitz.open() as lettering:
            page = document.new_page(width=500, height=260)
            page.insert_text((25, 63), "Compound No.", fontsize=9)
            page.insert_text((185, 63), "Structure", fontsize=9)
            heading = lettering.new_page(width=500, height=40)
            heading.insert_text((25, 30), title, fontsize=8)
            image = heading.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            page.insert_image(fitz.Rect(0, 0, 500, 40), stream=image.tobytes("png"))
            layout = source_layout(page)
            tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
            nominations = nominate_unruled_headers(tokens, [500, 260])
            self.assertEqual(len(nominations), 1)
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                return_value=(
                    "rapidocr",
                    title_fixtures.CatalogueTitleSourceTests.engine(title),
                ),
            ):
                scope = observe_unruled_header(
                    page,
                    tokens,
                    nominations[0],
                    hashlib.sha256(document.tobytes()).hexdigest(),
                )
            self.assertEqual(unruled_header_roles(scope)["role"], "nonfinal")

    def test_original_native_conflict_cannot_be_overwritten_by_two_optical_votes(self):
        title = "Table 62. Compounds"
        document, _structures, _boxes = raster_catalogue(title, entire_page=False)
        with document:
            document[0].insert_text((400, 85), "Intermediate", fontsize=10)
            _grids, _tokens, scope, _calls = self.observe(document, title)
            self.assertEqual(scope["role"], "unresolved")

    def test_shared_pixel_partition_keeps_the_existing_header_frame_contract(self):
        import numpy as np

        from patent_sar_extractor.core.cell_header_lines import (
            physical_line_frame,
            physical_row_bounds,
        )

        for dpi in (400, 600):
            with self.subTest(dpi=dpi):
                image = np.full((160, 100, 3), 255, dtype=np.uint8)
                image[10:30, 8:60] = 0
                self.assertIsNone(physical_line_frame(image, 0, dpi))
                image[70:90, 12:75] = 0
                expected = [[8, 10, 60, 30], [12, 70, 75, 90]]
                frame = physical_line_frame(image, 0, dpi)
                self.assertEqual(frame["row_bounds"], expected)
                self.assertEqual(
                    physical_row_bounds(
                        image.min(axis=2) < 180,
                        dpi,
                        maximum_rows=8,
                        maximum_row_height=12,
                    ),
                    (expected, None),
                )
                image[10:150, 8:60] = 0
                refused = physical_line_frame(image, 0, dpi)
                self.assertEqual(refused["status"], "unresolved")
                self.assertEqual(refused["row_bounds"], [])


if __name__ == "__main__":
    unittest.main()
