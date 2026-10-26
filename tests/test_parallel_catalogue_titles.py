"""Complete independent parallel titles, never nearest-frame role assignment."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.title_source_inventory import title_source_cells
from tests.parallel_catalogue_support import (
    TITLES,
    ParallelCatalogueControls,
    original_parallel_catalogues,
    title_reader,
)


class ParallelCatalogueTitleTests(ParallelCatalogueControls, unittest.TestCase):
    def test_native_parallel_titles_are_the_comparison_baseline(self):
        document, _structures, _boxes, frames = original_parallel_catalogues()
        with document:
            scopes = self.scopes(document, frames)
            self.assertEqual([s["role"] for s in scopes], ["compound", "nonfinal"])
            self.assertEqual([s["table_key"] for s in scopes], ["TABLEA", "TABLEB"])

    def test_outlined_parallel_titles_keep_both_independent_roles(self):
        document, _structures, _boxes, frames = original_parallel_catalogues("outlined")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ),
        ):
            scopes = self.scopes(document, frames)
            self.assertEqual([s["role"] for s in scopes], ["compound", "nonfinal"])
            self.assertEqual([s["table_key"] for s in scopes], ["TABLEA", "TABLEB"])
            for scope in scopes:
                self.assertEqual(
                    caption_role_status(scope, 1, scope["table_bbox"]), scope["role"]
                )

    def test_raster_parallel_titles_keep_both_independent_roles(self):
        document, _structures, _boxes, frames = original_parallel_catalogues("raster")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ),
        ):
            scopes = self.scopes(document, frames)
            self.assertEqual([s["role"] for s in scopes], ["compound", "nonfinal"])
            self.assertEqual([s["table_key"] for s in scopes], ["TABLEA", "TABLEB"])

    def test_only_the_proved_final_column_enters_the_binding_table(self):
        document, structures, boxes, frames = original_parallel_catalogues("outlined")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ) as reader,
        ):
            result = bind_caption_grids(
                document,
                structures,
                boxes,
                [1],
                grids_for_page=lambda page: frames,
                tokens_for_page=lambda page: SourceTokens(
                    source_layout(page).native, source_layout(page)
                ),
            )
            self.assertEqual([b["label"] for b in result.bindings], ["11A", "12A"])
            self.assertEqual(result.issues, [])
            self.assertEqual(len(result.exclusions), 1)
            self.assertEqual(
                result.exclusions[0]["structure_ids"], ["original-1-0", "original-1-1"]
            )
            self.assertEqual(reader.call_count, 2)

    def test_both_columns_require_independent_complete_markers(self):
        titles = ("Table A. Compounds", "and intermediates")
        document, _structures, _boxes, frames = original_parallel_catalogues(
            "outlined",
            titles=titles,
        )
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(titles),
            ),
        ):
            self.assertEqual(
                [s["role"] for s in self.scopes(document, frames)],
                ["unresolved", "unresolved"],
            )

    def test_same_printed_table_key_cannot_hide_different_roles(self):
        titles = ("Table A. Compounds", "Table A. Intermediates")
        document, _structures, _boxes, frames = original_parallel_catalogues(
            "outlined",
            titles=titles,
        )
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(titles),
            ),
        ):
            self.assertEqual(
                [s["role"] for s in self.scopes(document, frames)],
                ["unresolved", "unresolved"],
            )

    def test_unowned_negative_ink_cannot_be_omitted_between_columns(self):
        document, _structures, _boxes, frames = original_parallel_catalogues(
            "outlined",
            extra_title="and intermediates",
        )
        complete = "Table A. Compounds and intermediates Table B. Intermediates"
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                return_value=("rapidocr", title_reader(complete)),
            ),
        ):
            self.assertEqual(
                [s["role"] for s in self.scopes(document, frames)],
                ["unresolved", "unresolved"],
            )

    def test_missing_peer_observation_invalidates_the_whole_source_family(self):
        document, _structures, _boxes, frames = original_parallel_catalogues("raster")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ),
        ):
            scope = self.scopes(document, frames)[0]
            self.assertEqual(scope["role"], "compound")
            changed = json.loads(json.dumps(scope))
            parent = next(p for p in changed["sources"] if p["original_titles"])
            parent["original_titles"].pop()
            self.assertIsNone(caption_role_status(changed, 1, changed["table_bbox"]))

    def test_peer_original_changes_reject_the_final_column_without_new_ocr(self):
        document, _structures, _boxes, frames = original_parallel_catalogues("raster")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ),
        ):
            scope = self.scopes(document, frames)[0]
            cells = list(
                title_source_cells(
                    {
                        "source_sections": [
                            {
                                "role": "nonfinal_caption_catalog",
                                "caption_role": scope,
                            }
                        ]
                    }
                )
            )
            self.assertEqual(original_role_source_errors(document, cells), [])
            document[0].draw_rect(fitz.Rect(620, 80, 623, 84), fill=(0, 0, 0))
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Replay must not acquire OCR"),
            ):
                self.assertTrue(original_role_source_errors(document, cells))

    def test_staggered_or_open_unknown_source_windows_do_not_guess_an_owner(self):
        for options in ({"right_shift": 4}, {"open_right": True}):
            with self.subTest(options=options):
                document, _structures, _boxes, frames = original_parallel_catalogues(
                    "outlined",
                    **options,
                )
                with (
                    document,
                    patch(
                        "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                        side_effect=AssertionError("Unproved family must refuse first"),
                    ),
                ):
                    self.assertEqual(
                        [s["role"] for s in self.scopes(document, frames)],
                        ["unresolved", "unresolved"],
                    )

    def test_malformed_or_forged_peer_axes_cannot_authorize_a_saved_role(self):
        document, _structures, _boxes, frames = original_parallel_catalogues("outlined")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ),
        ):
            scope = self.scopes(document, frames)[0]
            for peers in (
                None,
                [],
                [None, None],
                [frames[0], frames[0]],
                [{"xs": [], "ys": []}, frames[1]],
            ):
                with self.subTest(peers=peers):
                    bad = copy.deepcopy(scope)
                    bad["parallel_grids"] = peers
                    self.assertIsNone(caption_role_status(bad, 1, bad["table_bbox"]))

    def test_one_weak_peer_cannot_publish_the_other_successful_column(self):
        from itertools import cycle

        choices = cycle(((TITLES[0], 0.99), (TITLES[1], 0.2)))
        document, _structures, _boxes, frames = original_parallel_catalogues("outlined")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=lambda: ("rapidocr", title_reader(*next(choices))),
            ),
        ):
            self.assertEqual(
                [s["role"] for s in self.scopes(document, frames)],
                ["unresolved", "unresolved"],
            )


if __name__ == "__main__":
    unittest.main()
