"""A fully observed local conflict never qualifies itself or waives weak peers."""

import copy
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.source_geometry import (
    SourceTokens,
    overlaps,
    source_layout,
)
from patent_sar_extractor.core.title_source_inventory import title_source_cells
from patent_sar_extractor.core.title_source_proof import (
    source_title_observation,
    source_title_text,
)
from tests.parallel_catalogue_support import (
    ParallelCatalogueControls,
    original_parallel_catalogues,
)


class ParallelTitleConflictTests(ParallelCatalogueControls, unittest.TestCase):
    def observed(
        self,
        *,
        native="Table B. Compounds",
        titles=("Table A. Compounds", "Table B. Intermediates"),
    ):
        document, _structures, _boxes, frames = original_parallel_catalogues(
            "raster", titles=titles
        )
        self.addCleanup(document.close)
        document[0].insert_text((400, 85), native, fontsize=9, render_mode=3)
        layout = source_layout(document[0])
        # Controlled raster locator words come from the generated pre-image,
        # not from the conflicting hidden native layer. Production uses the
        # same independent primary/native split; real OCR is covered separately.
        template, _rows, _boxes, _frames = original_parallel_catalogues(
            "native", titles=titles
        )
        with template:
            raster = [
                {
                    key: token[key]
                    for key in ("text", "x", "y", "bbox", "geometry_space")
                }
                | {"source": "raster", "confidence": 0.99}
                for token in source_layout(template[0]).native
                if token["bbox"][3] < 96
            ]
        primary = [
            t for t in layout.native if not overlaps(t["bbox"], layout.raster_bounds)
        ] + raster
        tokens = SourceTokens(primary, layout, layout.raster_bounds)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=self.readers(titles),
        ):
            scopes = [
                observe_caption_role(document[0], frame, frames, tokens)
                for frame in frames
            ]
        return document, scopes

    def conflict_record(self, scope):
        return next(
            record
            for parent in scope["sources"]
            for record in parent["original_titles"]
            if (observed := source_title_observation(record)) is not None
            and observed[1]
        )

    def test_complete_local_conflict_is_retained_and_cannot_confirm_its_own_column(
        self,
    ):
        document, scopes = self.observed()
        self.assertEqual([s["role"] for s in scopes], ["compound", "unresolved"])
        record = self.conflict_record(scopes[0])
        self.assertIsNone(source_title_text(record))
        self.assertEqual(
            source_title_observation(record), ("Table B. Intermediates", True)
        )
        self.assertEqual(len(record["observations"]), 2)
        sources = title_source_cells(
            {
                "source_sections": [
                    {"role": "nonfinal_caption_catalog", "caption_role": scopes[0]}
                ]
            }
        )
        self.assertEqual(original_role_source_errors(document, sources), [])

    def test_missing_or_weak_conflict_reads_cannot_certify_a_successful_peer(self):
        _document, scopes = self.observed()
        for operation in ("missing", "weak", "ownership"):
            scope = copy.deepcopy(scopes[0])
            record = self.conflict_record(scope)
            if operation == "missing":
                record["observations"].pop()
            elif operation == "weak":
                for reading in record["observations"]:
                    reading["confidence"] = 0.1
                    for part in reading["parts"]:
                        part["confidence"] = 0.1
            else:
                record["ink_source"]["row_index"] = 0
            with self.subTest(operation=operation):
                self.assertIsNone(caption_role_status(scope, 1, scope["table_bbox"]))

    def test_foreign_table_key_is_not_a_local_role_conflict_exception(self):
        _document, scopes = self.observed(native="Table X. Compounds")
        self.assertEqual([s["role"] for s in scopes], ["unresolved", "unresolved"])

    def test_competing_same_key_roles_remain_a_whole_family_conflict(self):
        _document, scopes = self.observed(
            native="Table A. Compounds",
            titles=("Table A. Compounds", "Table A. Intermediates"),
        )
        self.assertEqual([s["role"] for s in scopes], ["unresolved", "unresolved"])

    def test_peer_source_change_is_replayed_without_another_reader(self):
        document, scopes = self.observed()
        sources = list(
            title_source_cells(
                {
                    "source_sections": [
                        {"role": "nonfinal_caption_catalog", "caption_role": scopes[0]}
                    ]
                }
            )
        )
        document[0].draw_line((410, 80), (500, 80), width=2)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError("Readback must not start OCR"),
        ):
            self.assertTrue(original_role_source_errors(document, sources))


if __name__ == "__main__":
    unittest.main()
