"""Bounded raster observation, source disagreement and typed cache receipts."""

import copy
import unittest
from unittest.mock import Mock, patch

import fitz
from test_hybrid_source_native import hybrid_page

from patent_sar_extractor.core import page_ocr_cache, table_geometry
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.source_cache_policy import preserved_source_provenance
from patent_sar_extractor.core.source_geometry import source_layout


class HybridSourceBoundaryTests(unittest.TestCase):
    def test_one_raster_window_keeps_independent_native_evidence(self):
        doc, page = hybrid_page(shadow="12.5")
        with (
            doc,
            patch.object(
                table_geometry, "ocr_tokens_with_positions", return_value=[]
            ) as reader,
        ):
            tokens = table_geometry.page_tokens(page)
            expected = source_layout(page).raster_bounds
        reader.assert_called_once()
        self.assertEqual(tuple(reader.call_args.kwargs["bounds"]), expected)
        self.assertTrue(any(t["text"] == "12.5" for t in tokens.native_tokens))
        self.assertFalse(any(t["text"] == "12.5" for t in tokens))

    def test_invalid_or_excessive_original_layout_is_not_silently_accepted(self):
        for bounds in ((0, 0, True, 50), (0, 0, float("nan"), 50), (1, 1, 1, 5)):
            with fitz.open() as doc:
                page = doc.new_page()
                with (
                    patch.object(
                        page, "get_image_info", return_value=[{"bbox": bounds}]
                    ),
                    self.assertRaises(ValueError),
                ):
                    source_layout(page)
        with fitz.open() as doc:
            page = doc.new_page()
            with (
                patch.object(page, "get_image_info", return_value=[{}] * 4097),
                self.assertRaises(ValueError),
            ):
                source_layout(page)

    def test_no_engine_cannot_publish_footer_only_as_complete_hybrid_cache(self):
        doc, page = hybrid_page()
        with (
            doc,
            patch.object(page_ocr_cache, "get_ocr_engine", return_value=False),
            self.assertRaises(RuntimeError),
        ):
            page_ocr_cache._page_payload(page, min_native_chars=1)

    def test_valid_header_conflict_cannot_fall_through_to_an_api_role_resolver(self):
        doc, page = hybrid_page()
        resolver = Mock()

        def conflict(_page, _region, _schema, *, tokens, evidence_sink):
            evidence_sink.append(
                {"status": "unresolved", "conflicting_columns": [1], "observations": []}
            )

        with (
            doc,
            patch(
                "patent_sar_extractor.core.activity_coordinates.refine_scanned_header",
                side_effect=conflict,
            ),
        ):
            result = extract_coordinate_tables(
                doc, [page.number], header_resolver=resolver
            )
        resolver.assert_not_called()
        self.assertEqual(result.rows, [])
        self.assertTrue(any(c["status"] == "unresolved" for c in result.coverage))

    def test_inherited_raw_provenance_rejects_incomplete_or_untyped_receipts(self):
        metadata = {
            "page_count": 2,
            "inherited_observation_contract": {
                "name": "patentsar.page-ocr-observation",
                "version": 1,
            },
            "source_policy_validation": {
                "policy_version": 2,
                "checked_pages": [0],
                "native_raster_pages": [],
            },
        }
        self.assertTrue(preserved_source_provenance(metadata))
        for field, value in (
            ("policy_version", True),
            ("checked_pages", [True]),
            ("checked_pages", [0, 0]),
            ("native_raster_pages", [1]),
        ):
            changed = copy.deepcopy(metadata)
            changed["source_policy_validation"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                preserved_source_provenance(changed)
