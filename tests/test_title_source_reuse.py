"""Call-local source reads conserve weak attempts and recheck original pixels."""

import copy
import unittest
from itertools import cycle
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.title_source_proof import MAX_TITLE_SOURCES
from tests.parallel_catalogue_support import (
    TITLES,
    ParallelCatalogueControls,
    original_parallel_catalogues,
    title_reader,
)


class TitleSourceReuseTests(ParallelCatalogueControls, unittest.TestCase):
    def test_weak_attempts_are_reused_not_retried_until_a_role_appears(self):
        readings = cycle(((TITLES[0], 0.99), (TITLES[1], 0.2), (TITLES[1], 0.99)))
        document, _structures, _boxes, frames = original_parallel_catalogues("raster")
        cache = {}
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=lambda: ("rapidocr", title_reader(*next(readings))),
            ) as reader,
        ):
            scopes = self.scopes(document, frames, title_cache=cache)
            self.assertEqual([scope["role"] for scope in scopes], ["unresolved"] * 2)
            self.assertEqual(reader.call_count, 2)
            self.assertEqual(len(cache), 2)
            records = [
                next(
                    title
                    for parent in scope["sources"]
                    for title in parent["original_titles"]
                )
                for scope in scopes
            ]
            self.assertIsNot(records[0]["observations"], records[1]["observations"])

    def test_changed_original_refuses_before_any_new_title_reader(self):
        document, _structures, _boxes, frames = original_parallel_catalogues("raster")
        cache = {}
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ) as reader,
        ):
            page = document[0]
            tokens = SourceTokens(source_layout(page).native, source_layout(page))
            self.assertEqual(
                observe_caption_role(
                    page, frames[0], frames, tokens, title_cache=cache
                )["role"],
                "compound",
            )
            page.draw_rect(fitz.Rect(620, 80, 623, 84), fill=(0, 0, 0))
            with self.assertRaises(ValueError):
                observe_caption_role(page, frames[1], frames, tokens, title_cache=cache)
            self.assertEqual(reader.call_count, 2)

    def test_malformed_or_oversized_call_local_inventory_refuses_before_ocr(self):
        document, _structures, _boxes, frames = original_parallel_catalogues("outlined")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Invalid reuse state must refuse first"),
            ),
        ):
            for cache in ([], {index: None for index in range(MAX_TITLE_SOURCES + 1)}):
                with self.subTest(kind=type(cache)), self.assertRaises(ValueError):
                    self.scopes(document, frames, title_cache=cache)

    def test_native_optional_peer_inventory_cannot_be_downgraded_to_null(self):
        from patent_sar_extractor.core.caption_role_proof import caption_role_status

        document, _structures, _boxes, frames = original_parallel_catalogues()
        with document:
            scope = copy.deepcopy(self.scopes(document, frames)[0])
            scope["parallel_grids"] = None
            self.assertIsNone(caption_role_status(scope, 1, scope["table_bbox"]))


if __name__ == "__main__":
    unittest.main()
