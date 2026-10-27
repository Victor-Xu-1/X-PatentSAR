"""Call-local source reads conserve weak attempts and recheck original pixels."""

import copy
import unittest
from itertools import cycle
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import title_ink_geometry
from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.title_geometry_memo import (
    memoized_title_geometry,
    title_geometry_call,
)
from patent_sar_extractor.core.title_ink_geometry import title_ink_rows
from patent_sar_extractor.core.title_source_proof import MAX_TITLE_SOURCES
from tests.parallel_catalogue_support import (
    TITLES,
    ParallelCatalogueControls,
    original_parallel_catalogues,
    title_reader,
)


class TitleSourceReuseTests(ParallelCatalogueControls, unittest.TestCase):
    def test_geometry_memo_obeys_the_existing_source_bound(self):
        calls = []

        def calculate(packet):
            calls.append(packet["value"])
            return [{"value": packet["value"]}]

        @title_geometry_call
        def read():
            for value in range(MAX_TITLE_SOURCES + 1):
                memoized_title_geometry({"value": value}, calculate)
            memoized_title_geometry({"value": 0}, calculate)

        read()
        self.assertEqual(len(calls), MAX_TITLE_SOURCES + 2)

    def test_geometry_memo_rehashes_mutations_copies_results_and_expires(self):
        calls = []

        def calculate(packet):
            calls.append(copy.deepcopy(packet))
            return [{"value": packet["value"]}]

        @title_geometry_call
        def read():
            packet = {"value": 1}
            first = memoized_title_geometry(packet, calculate)
            first[0]["value"] = 99
            self.assertEqual(
                memoized_title_geometry(copy.deepcopy(packet), calculate),
                [{"value": 1}],
            )
            self.assertEqual(len(calls), 1)
            packet["value"] = 2
            self.assertEqual(memoized_title_geometry(packet, calculate), [{"value": 2}])
            self.assertEqual(len(calls), 2)

        read()
        self.assertEqual(
            memoized_title_geometry({"value": 1}, calculate), [{"value": 1}]
        )
        self.assertEqual(len(calls), 3)

        @title_geometry_call
        def interrupted():
            memoized_title_geometry({"value": 1}, calculate)
            raise RuntimeError("controlled interruption")

        with self.assertRaises(RuntimeError):
            interrupted()
        memoized_title_geometry({"value": 1}, calculate)
        self.assertEqual(len(calls), 5)

    def test_warm_geometry_still_rejects_changed_original_pixel_proof(self):
        document, _, _, frames = original_parallel_catalogues("native")
        with document:
            scope = self.scopes(document, frames)[0]
            source = scope["sources"][0]["title_context"]["ink_source"]

            @title_geometry_call
            def validate():
                with patch.object(
                    title_ink_geometry,
                    "_title_ink_rows",
                    wraps=title_ink_geometry._title_ink_rows,
                ) as compute:
                    original = title_ink_rows(source)
                    self.assertIsNotNone(original)
                    self.assertEqual(title_ink_rows(copy.deepcopy(source)), original)
                    self.assertEqual(compute.call_count, 1)
                    bad = copy.deepcopy(source)
                    bad["ruling_sources"][0]["pixels"]["readings"][0][
                        "pixel_sha256"
                    ] = "0" * 64
                    title_ink_rows(bad)
                    self.assertEqual(compute.call_count, 2)
                    # Geometry cannot reconstruct RGB from a retained ink mask.
                    # The unchanged actual-original replayer still rejects it.
                    context = copy.deepcopy(scope["sources"][0]["title_context"])
                    context["ink_source"] = bad
                    self.assertTrue(
                        original_role_source_errors(
                            document,
                            [
                                (
                                    1,
                                    {
                                        "method": "original_title_context",
                                        "title_context": context,
                                    },
                                )
                            ],
                        )
                    )
                    bad["ruling_sources"][0]["pixels"]["readings"][0]["mask_hex"] = "00"
                    self.assertIsNone(title_ink_rows(bad))

            validate()

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
