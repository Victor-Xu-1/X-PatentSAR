"""Derived source proof changes cannot relabel historical scientific products."""

import copy
import unittest
from unittest.mock import patch

from test_web_support import WebFixture, artifact_run

from patent_sar_extractor import contracts
from patent_sar_extractor.core import page_ocr_cache
from patent_sar_extractor.web.acceptance import authority, current


class CellObservationEpochTests(WebFixture, unittest.TestCase):
    def test_older_binding_or_activity_proof_remains_unchanged_historical_review(self):
        from patent_sar_extractor.web.artifacts import ArtifactView

        root = artifact_run(self.root / "controlled-old-cell-proof", self.pdf, rows=1)
        view = ArtifactView.read(root)
        for name in ("bindings", "activity"):
            payloads = copy.deepcopy(view.payloads)
            payloads[name]["schema"]["version"] -= 1
            original = copy.deepcopy(payloads)
            self.assertFalse(current(payloads[name], name))
            result, historical = authority(payloads, pdf_verified=True, marker=None)
            self.assertEqual(result.state, "historical")
            self.assertTrue(historical)
            self.assertEqual(payloads, original)

    def test_cell_semantic_schema_changes_do_not_invalidate_original_page_ocr(self):
        metadata = page_ocr_cache.build_cache_metadata(str(self.pdf))
        self.assertEqual(
            metadata["schema"]["version"], contracts.PAGE_OCR_CACHE_SCHEMA_VERSION
        )
        self.assertNotIn("structure_binder_version", metadata)
        self.assertNotIn("activity_extractor_version", metadata)
        payload = {
            "metadata": metadata,
            "page_texts": {"0": "Original caption"},
            "ocr_line_map": {"0": []},
        }
        before = copy.deepcopy(payload)
        with patch.object(
            page_ocr_cache,
            "get_ocr_engine",
            side_effect=AssertionError("No inference needed for raw identity"),
        ):
            self.assertTrue(page_ocr_cache.cache_matches_pdf(payload, str(self.pdf)))
        self.assertEqual(payload, before)
