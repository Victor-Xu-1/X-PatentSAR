"""One original physical title shared by numbered rows and declaration coverage."""

import copy
import unittest
from itertools import cycle
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_context_geometry import grid_box
from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.ruled_structure_headers import observe_ruled_header
from patent_sar_extractor.core.source_document import document_sha256
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.structure_catalogue_headers import header_catalogue_scope
from patent_sar_extractor.core.structure_column_anchors import (
    ANCHOR_ROLE,
    observe_column_anchor,
)
from patent_sar_extractor.core.structure_declaration_catalogues import (
    catalogue_scopes_for_grids,
)
from patent_sar_extractor.core.structure_declaration_scopes import declaration_scopes
from patent_sar_extractor.core.structure_declarations import observe_declaration_pages
from tests.parallel_catalogue_support import (
    TITLES,
    ParallelCatalogueControls,
    original_parallel_catalogues,
    title_reader,
)


class StructureCatalogueHeaderTests(ParallelCatalogueControls, unittest.TestCase):
    def source(self, *, mode="native", titles=TITLES):
        document, by_page, _boxes, grids = original_parallel_catalogues(
            mode, titles=titles, headers=True
        )
        temporary = TemporaryDirectory(prefix="catalogue-header-original-")
        self.addCleanup(temporary.cleanup)
        original = Path(temporary.name) / "original.pdf"
        with document:
            document.save(original)
        document = fitz.open(original)
        self.addCleanup(document.close)
        page = document[0]
        layout = source_layout(page)
        tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
        sha = document_sha256(document)
        diagrams = [
            {"id": row["id"], "bbox": [row[k] for k in ("x0", "y0", "x1", "y1")]}
            for row in by_page[1]
        ]
        columns, cache = [], {}
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=self.readers(titles),
        ):
            for grid in grids:
                header = observe_ruled_header(
                    page, tokens, grid, sha, grids=grids, title_cache=cache
                )
                source = observe_column_anchor(tokens, header, diagrams, grid=grid)
                columns.append(
                    {
                        "role": ANCHOR_ROLE,
                        "status": source["status"],
                        "page_no": 1,
                        "region_id": proof_id(source),
                        "source": source,
                    }
                )
        return document, by_page[1], grids, tokens, sha, columns

    def test_native_and_raster_titles_reuse_the_same_original_sources_without_ocr(self):
        for mode in ("native", "raster"):
            with self.subTest(mode=mode):
                _doc, _diagrams, grids, _tokens, sha, columns = self.source(mode=mode)
                with patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=AssertionError("Title adapter must not read again"),
                ):
                    scopes = catalogue_scopes_for_grids(
                        1, grids, {}, column_sections=columns, original_pdf_sha256=sha
                    )
                self.assertEqual([s["role"] for s in scopes], ["compound", "nonfinal"])
                self.assertEqual([s["table_key"] for s in scopes], ["TABLEA", "TABLEB"])
                for scope, column in zip(scopes, columns, strict=True):
                    self.assertIs(
                        scope["sources"],
                        column["source"]["header_scope"]["context_sources"],
                    )
                    self.assertEqual(
                        caption_role_status(scope, 1, scope["table_bbox"]),
                        scope["role"],
                    )

    def test_complete_declaration_page_uses_proved_headers_without_new_title_reads(
        self,
    ):
        doc, diagrams, grids, tokens, _sha, columns = self.source(mode="raster")
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError(
                "Declaration must share the original header title"
            ),
        ):
            sections, withheld = observe_declaration_pages(
                doc,
                diagrams,
                [0],
                {0: "Compound No. Structure"},
                lambda _p: tokens,
                grids_for_page=lambda _p: grids,
                caption_roles={},
                column_sections=columns,
            )
        self.assertEqual(len(sections), 1)
        scopes = declaration_scopes(sections[0]["source"])
        self.assertEqual([s["role"] for s in scopes], ["compound", "nonfinal"])
        self.assertTrue(all(not s["unproved_title"] for s in scopes))
        self.assertEqual(withheld, {"original-1-0"})

    def test_header_words_cannot_turn_an_unknown_title_into_a_compound_title(self):
        _doc, _diagrams, _grids, _tokens, sha, columns = self.source(
            titles=("Table A. Observations", "Table B. Observations")
        )
        scopes = [header_catalogue_scope(c, sha) for c in columns]
        self.assertEqual([s["role"] for s in scopes], ["unknown", "unknown"])

    def test_foreign_identity_changed_owner_and_foreign_page_are_rejected(self):
        _doc, _diagrams, grids, _tokens, sha, columns = self.source()
        with self.assertRaises(ValueError):
            header_catalogue_scope(columns[0], "b" * 64)
        for field, value in (
            ("region_id", "c" * 64),
            ("page_no", True),
            ("status", "accepted"),
        ):
            changed = copy.deepcopy(columns[0])
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                header_catalogue_scope(changed, sha)
        with self.assertRaises(ValueError):
            catalogue_scopes_for_grids(
                2, grids, {}, column_sections=columns, original_pdf_sha256=sha
            )

    def test_an_existing_weak_catalogue_cannot_be_overruled_by_a_later_header(self):
        doc, _diagrams, grids, tokens, sha, columns = self.source(mode="raster")
        values = cycle(TITLES)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=lambda: (
                "rapidocr",
                title_reader(next(values), confidence=0.6),
            ),
        ):
            prior = observe_caption_role(doc[0], grids[0], grids, tokens)
        self.assertEqual(prior["role"], "unresolved")
        self.assertEqual(
            caption_role_status(prior, 1, grid_box(grids[0])), "unresolved"
        )
        scopes = catalogue_scopes_for_grids(
            1,
            grids,
            {(1, tuple(grid_box(grids[0]))): prior},
            column_sections=columns,
            original_pdf_sha256=sha,
        )
        self.assertIs(scopes[0], prior)
        self.assertEqual(scopes[0]["role"], "unresolved")


if __name__ == "__main__":
    unittest.main()
