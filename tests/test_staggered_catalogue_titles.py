"""Different actual table tops cannot mix peer body ink with original titles."""

import json
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from tests.parallel_catalogue_support import TITLES, ParallelCatalogueControls
from tests.staggered_catalogue_support import staggered_catalogues


class StaggeredCatalogueTitleTests(ParallelCatalogueControls, unittest.TestCase):
    def test_native_staggered_sources_are_the_zero_ocr_baseline(self):
        for shift in (-35, 4, 60):
            with self.subTest(shift=shift):
                document, _, _, frames = staggered_catalogues(shift=shift)
                with (
                    document,
                    patch(
                        "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                        side_effect=AssertionError(
                            "Native title baseline must remain zero-OCR"
                        ),
                    ),
                ):
                    scopes = self.scopes(document, frames)
                    self.assertEqual(
                        [s["role"] for s in scopes], ["compound", "nonfinal"]
                    )

    def test_complete_outlined_and_raster_staggered_titles_qualify_both_members(self):
        for mode in ("outlined", "raster"):
            for shift in (-35, 4, 60):
                with self.subTest(mode=mode, shift=shift):
                    document, _, _, frames = staggered_catalogues(mode, shift=shift)
                    literals = TITLES[::-1] if shift < 0 else TITLES
                    with (
                        document,
                        patch(
                            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                            side_effect=self.readers(literals),
                        ),
                    ):
                        scopes = json.loads(json.dumps(self.scopes(document, frames)))
                        self.assertEqual(
                            [s["role"] for s in scopes], ["compound", "nonfinal"]
                        )
                        self.assertEqual(
                            [s["table_key"] for s in scopes], ["TABLEA", "TABLEB"]
                        )
                        self.assertEqual(
                            [
                                caption_role_status(s, 1, s["table_bbox"])
                                for s in scopes
                            ],
                            ["compound", "nonfinal"],
                        )

    def test_actual_binder_retains_staggered_nonfinal_exclusion_without_reading_its_structures(
        self,
    ):
        document, structures, boxes, frames = staggered_catalogues("raster")
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
            self.assertEqual(
                result.exclusions[0]["structure_ids"], ["original-1-0", "original-1-1"]
            )
            self.assertEqual(reader.call_count, 2)


if __name__ == "__main__":
    unittest.main()
