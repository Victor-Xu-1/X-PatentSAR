"""Parallel original titles feed the same ruled-column and source consumers."""

import copy
import json
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.role_text_sources import role_text_cells
from patent_sar_extractor.core.ruled_structure_headers import (
    observe_ruled_header,
    ruled_header_roles,
)
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.structure_catalogs import catalog_for_scope
from tests.parallel_catalogue_support import (
    ParallelCatalogueControls,
    original_parallel_catalogues,
)


class ParallelStructureHeaderTests(ParallelCatalogueControls, unittest.TestCase):
    def headers(self, document, frames, *, title_cache=None):
        page = document[0]
        layout = source_layout(page)
        tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
        return [
            observe_ruled_header(
                page, tokens, frame, "a" * 64, grids=frames, title_cache=title_cache
            )
            for frame in frames
        ]

    def test_outlined_and_raster_title_roles_reach_saved_column_consumers(self):
        for mode in ("outlined", "raster"):
            with self.subTest(mode=mode):
                document, _structures, _boxes, frames = original_parallel_catalogues(
                    mode, headers=True
                )
                with (
                    document,
                    patch(
                        "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                        side_effect=self.readers(),
                    ) as reader,
                ):
                    headers = json.loads(
                        json.dumps(self.headers(document, frames, title_cache={}))
                    )
                    self.assertEqual(
                        [ruled_header_roles(h)["role"] for h in headers],
                        ["compound", "nonfinal"],
                    )
                    self.assertEqual(
                        [catalog_for_scope(h).identifier for h in headers],
                        ["Table A", "Table B"],
                    )
                    payload = {
                        "source_sections": [
                            {
                                "role": "structure_column_anchor",
                                "page_no": 1,
                                "source": {"header_scope": h},
                            }
                            for h in headers
                        ]
                    }
                    self.assertEqual(
                        original_role_source_errors(document, role_text_cells(payload)),
                        [],
                    )
                    self.assertEqual(reader.call_count, 2)

    def test_native_parallel_headers_require_typed_peer_inventory(self):
        document, _structures, _boxes, frames = original_parallel_catalogues(
            headers=True
        )
        with document:
            headers = self.headers(document, frames)
            self.assertEqual(
                [ruled_header_roles(h)["role"] for h in headers],
                ["compound", "nonfinal"],
            )
            bad = copy.deepcopy(headers[0])
            bad["parallel_grids"] = None
            with self.assertRaises(ValueError):
                ruled_header_roles(bad)


if __name__ == "__main__":
    unittest.main()
