"""Original-ink catalogue discovery, ownership, refusal and consumer replay."""

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
from tests.test_catalogue_title_source import original_catalogue


def outline_lines(page, rows):
    with fitz.open() as lettering:
        source = lettering.new_page(width=page.rect.width, height=page.rect.height)
        for x, y, text, size in rows:
            source.insert_text((x, y), text, fontsize=size)
        with (
            fitz.open(
                stream=source.get_svg_image(text_as_path=True).encode(), filetype="svg"
            ) as image,
            fitz.open(stream=image.convert_to_pdf(), filetype="pdf") as paths,
        ):
            assert not paths[0].get_text().strip()
            page.show_pdf_page(page.rect, paths, 0)


class TitleInkDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.factory = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError(
                    "No native model evaluation in source regressions"
                ),
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

    def observe(self, document, text, *, tokens=None, prohibit_reader=False):
        page = document[0]
        if tokens is None:
            layout = source_layout(page)
            tokens = SourceTokens(layout.native, layout)
        grids = detect_ruled_table_regions(page, dpi=240)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError("Source refused before text reader")
            if prohibit_reader
            else None,
            return_value=(
                "rapidocr",
                title_fixtures.CatalogueTitleSourceTests.engine(text),
            ),
        ) as reader:
            scope = observe_caption_role(page, grids[0], grids, tokens)
        return grids, tokens, scope, reader.call_count

    def test_serialized_ink_only_title_replays_and_cannot_drop_a_required_row(self):
        document, _structures, _boxes = original_catalogue(fully_outlined=True)
        with document:
            _grids, _tokens, scope, calls = self.observe(
                document, "Table 47. Intermediate Compounds"
            )
            self.assertEqual(scope["observations"], [])
            self.assertEqual(scope["role"], "nonfinal")
            self.assertEqual(calls, 1)
            scope = json.loads(json.dumps(scope))
            self.assertEqual(
                caption_role_status(scope, 1, scope["table_bbox"]), "nonfinal"
            )
            proof = next(
                record
                for parent in scope["sources"]
                for record in parent["original_titles"]
            )
            replay_source_title(document[0], proof)
            changed = copy.deepcopy(scope)
            for parent in changed["sources"]:
                parent["original_titles"].clear()
            self.assertIsNone(caption_role_status(changed, 1, changed["table_bbox"]))
            for field in ("native_window", "ruling_sources", "context"):
                bad = copy.deepcopy(scope)
                bad["sources"][0]["title_context"]["ink_source"].pop(field)
                self.assertIsNone(caption_role_status(bad, 1, bad["table_bbox"]))

    def test_original_ink_mutation_rejects_source_before_numbered_recognition(self):
        document, _structures, _boxes = original_catalogue(fully_outlined=True)
        with document:
            _grids, _tokens, scope, _calls = self.observe(
                document, "Table 47. Intermediate Compounds"
            )
            payload = {
                "source_sections": [
                    {
                        "role": "nonfinal_caption_catalog",
                        "caption_role": scope,
                    }
                ]
            }
            sources = list(title_source_cells(payload))
            self.assertEqual(
                {cell["method"] for _, cell in sources},
                {"original_title", "original_title_context"},
            )
            self.assertEqual(original_role_source_errors(document, sources), [])
            document[0].draw_rect(fitz.Rect(53, 80, 55, 82), fill=(0, 0, 0))
            self.assertTrue(original_role_source_errors(document, sources))

    def test_reusing_an_ink_only_title_never_acquires_another_text_reader(self):
        document, _structures, boxes = original_catalogue(fully_outlined=True)
        with document:
            grids, tokens, scope, _calls = self.observe(
                document, "Table 47. Intermediate Compounds"
            )
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Reuse cannot acquire OCR"),
            ):
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

    def test_missing_table_word_is_recovered_without_overwriting_native_role(self):
        document, _structures, _boxes = catalog(None, prefixed=True)
        with document:
            document[0].insert_text((110, 85), "Intermediate Compounds", fontsize=10)
            outline_lines(document[0], [(50, 85, "Table 59.", 10)])
            _grids, _tokens, scope, _calls = self.observe(
                document, "Table 59. Intermediate Compounds"
            )
            self.assertEqual(
                [packet["text"] for packet in scope["observations"]],
                ["Intermediate Compounds"],
            )
            self.assertEqual(scope["role"], "nonfinal")
            self.assertEqual(scope["table_key"], "TABLE59")
            proof = next(
                record
                for parent in scope["sources"]
                for record in parent["original_titles"]
            )
            self.assertEqual(
                proof["nomination_source"]["text"], "Intermediate Compounds"
            )
            self.assertEqual(proof["native_source"]["text"], "Intermediate Compounds")
            replay_source_title(document[0], proof)

    def test_full_outline_compound_title_reaches_catalogue_consumers(self):
        document, structures, boxes = catalog(None, prefixed=True)
        with document:
            outline_lines(document[0], [(50, 85, "Table 83. Selected Compounds", 10)])
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                return_value=(
                    "rapidocr",
                    title_fixtures.CatalogueTitleSourceTests.engine(
                        "Table 83. Selected Compounds"
                    ),
                ),
            ):
                result = bind_caption_grids(document, structures, boxes, [1])
            self.assertEqual(len(result.bindings), 2)
            self.assertEqual(result.issues, [])
            scope = result.bindings[0]["ownership"]["caption_role"]
            catalogue = catalog_for_caption_scope(scope)
            self.assertEqual(catalogue.identifier, "Table 83")
            self.assertTrue(catalogue.selected_subset)

    def test_an_unnumbered_category_title_never_invents_a_table_identifier(self):
        for outlined in (False, True):
            with self.subTest(outlined=outlined):
                document, _structures, _boxes = catalog(None, prefixed=True)
                with document:
                    if outlined:
                        outline_lines(
                            document[0], [(50, 85, "Intermediate compounds", 10)]
                        )
                    else:
                        document[0].insert_text(
                            (50, 85), "Intermediate compounds", fontsize=10
                        )
                    _grids, _tokens, scope, _calls = self.observe(
                        document, "Intermediate compounds"
                    )
                    self.assertEqual(scope["role"], "nonfinal")
                    self.assertEqual(scope["table_key"], "")

    def test_unruled_columns_discover_an_outlined_title_without_a_word_locator(self):
        import hashlib

        from patent_sar_extractor.core.logical_column_partitions import (
            nominate_unruled_headers,
        )
        from patent_sar_extractor.core.unruled_structure_headers import (
            observe_unruled_header,
            unruled_header_roles,
        )

        with fitz.open() as document:
            page = document.new_page(width=500, height=260)
            page.insert_text((25, 63), "Compound No.", fontsize=9)
            page.insert_text((185, 63), "Structure", fontsize=9)
            title = "Table F. Intermediate compounds"
            outline_lines(page, [(25, 30, title, 8)])
            layout = source_layout(page)
            tokens = SourceTokens(layout.native, layout)
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
                roles = unruled_header_roles(scope)
            self.assertIsNotNone(roles)
            self.assertEqual(roles["role"], "nonfinal")

    def test_wrapped_unnumbered_categories_cannot_discard_the_other_role(self):
        for first, second in (
            ("Compounds", "Intermediates"),
            ("Intermediates", "Compounds"),
        ):
            with self.subTest(first=first), fitz.open() as document:
                page = document.new_page()
                original, _structures, _boxes = catalog(None, prefixed=True)
                with original:
                    page.show_pdf_page(page.rect, original, 0)
                page.insert_text((50, 70), first, fontsize=10)
                page.insert_text((50, 85), second, fontsize=10)
                _grids, _tokens, scope, _calls = self.observe(
                    document, f"{first} {second}"
                )
                self.assertIn(scope["role"], {"mixed", "conflict", "unresolved"})

    def test_unknown_row_budget_refuses_before_reader_acquisition(self):
        document, _structures, _boxes = catalog(None, prefixed=True)
        with document:
            outline_lines(
                document[0],
                [(50, 8 + 9 * index, f"Original row {index}", 5) for index in range(9)],
            )
            _grids, _tokens, scope, calls = self.observe(
                document, "", prohibit_reader=True
            )
            self.assertEqual(calls, 0)
            self.assertEqual(scope["role"], "unresolved")
            source = scope["sources"][0]["title_context"]["ink_source"]
            self.assertEqual(title_ink_rows(source)[1], "title_row_budget")

    def test_crossing_original_paint_cannot_be_clipped_into_a_title(self):
        document, _structures, _boxes = original_catalogue(fully_outlined=True)
        with document:
            document[0].draw_rect(fitz.Rect(350, 80, 370, 110), fill=(0, 0, 0))
            _grids, _tokens, scope, calls = self.observe(
                document, "", prohibit_reader=True
            )
            self.assertEqual(calls, 0)
            self.assertEqual(scope["role"], "unresolved")

    def test_raster_context_without_word_nominations_is_explicitly_unresolved(self):
        document, _structures, _boxes = original_catalogue(fully_outlined=True)
        with document:
            pixels = document[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            size = tuple(document[0].rect)
        with fitz.open() as raster:
            page = raster.new_page(width=size[2], height=size[3])
            page.insert_image(page.rect, stream=pixels.tobytes("png"))
            layout = source_layout(page)
            tokens = SourceTokens([], layout, tuple(page.rect))
            _grids, _tokens, scope, calls = self.observe(
                raster, "", tokens=tokens, prohibit_reader=True
            )
            self.assertEqual(calls, 0)
            self.assertEqual(scope["role"], "unresolved")

    def test_general_page_inventory_cannot_start_a_title_read_without_a_context_owner(
        self,
    ):
        from patent_sar_extractor.core.source_observations import (
            source_cell_observation,
        )
        from patent_sar_extractor.core.title_source_capture import attach_title_sources

        document, _structures, _boxes = original_catalogue(fully_outlined=True)
        with document:
            page = document[0]
            layout = source_layout(page)
            parent = source_cell_observation(
                SourceTokens(layout.native, layout), list(page.rect), native=True
            )
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError(
                    "Whole-page inventory is not a title reader"
                ),
            ):
                observed = attach_title_sources(page, [parent], [])
            self.assertIsNone(observed[0]["title_context"]["ink_source"])
            self.assertEqual(observed[0]["original_titles"], [])

    def test_declaration_chunks_keep_separate_parent_windows_without_extra_ocr(self):
        from patent_sar_extractor.core.source_observations import (
            source_cell_observation,
        )
        from patent_sar_extractor.core.title_source_capture import attach_title_sources

        with fitz.open() as document:
            page = document.new_page(width=400, height=300)
            page.insert_text((20, 50), "Table 5. Compounds", fontsize=10)
            layout = source_layout(page)
            tokens = SourceTokens(layout.native, layout)
            parents = [
                source_cell_observation(tokens, [0, top, 400, top + 100], native=True)
                for top in (0, 100, 200)
            ]
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError(
                    "Complete native declarations cannot load OCR"
                ),
            ):
                observed = attach_title_sources(page, parents, [parents[0]])
            self.assertEqual(
                [len(parent["original_titles"]) for parent in observed], [1, 0, 0]
            )
            self.assertEqual(
                [parent["bbox"] for parent in observed],
                [parent["bbox"] for parent in parents],
            )

    def test_malformed_source_owners_are_explicit_refusals_not_silently_empty(self):
        for payload in (
            {"source_sections": [None]},
            {
                "source_sections": [
                    {"role": "nonfinal_caption_catalog", "caption_role": {}}
                ]
            },
            {"source_sections": [{"role": "structure_column_anchor", "source": None}]},
            {
                "source_sections": [
                    {
                        "role": "structure_declaration_page",
                        "source": {"page_context": [None]},
                    }
                ]
            },
            {"source_role_observations": []},
            {"source_role_observations": {"bad": None}},
            {
                "source_role_observations": {
                    "bad": {"kind": "binding_proposal", "proposal": None}
                }
            },
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaises((ValueError, TypeError)),
            ):
                list(title_source_cells(payload))


if __name__ == "__main__":
    unittest.main()
