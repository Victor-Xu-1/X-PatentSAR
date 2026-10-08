"""Actual raw OCR/segmentation inputs remain reusable across release labels only."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_segmentation_checkpoint as segment_cases
from test_web_support import WebFixture

from patent_sar_extractor import contracts as core
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core import page_ocr_cache as caches
from patent_sar_extractor.workers.segmentation_checkpoint import verified_input


class ReleaseRawCacheTests(WebFixture, unittest.TestCase):
    def test_old_release_raw_ocr_is_reused_without_inference_or_source_rewrite(self):
        with patch.object(core, "__version__", "0.1.0"):
            metadata = caches.build_cache_metadata(str(self.pdf))
        source = self.root / "original-cache.json"
        payload = {
            "metadata": metadata,
            "page_texts": {"0": "Controlled original observation"},
            "ocr_line_map": {"0": []},
        }
        write_json_atomic(source, payload)
        before = source.read_bytes()
        target = self.root / "fresh" / "page_ocr_cache.json"
        with (
            patch.object(core, "__version__", "0.2.0"),
            patch.object(
                caches, "get_ocr_engine", side_effect=AssertionError("No model may run")
            ),
        ):
            self.assertTrue(caches.cache_matches_pdf(payload, str(self.pdf)))
            self.assertTrue(
                caches.inherit_page_ocr_cache(str(source), str(target), str(self.pdf))
            )
            result = caches.update_page_ocr_cache(str(self.pdf), [0], str(target))
        self.assertEqual(result["page_texts"], payload["page_texts"])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(json.loads(before)["metadata"]["product"]["version"], "0.1.0")

    def test_raw_ocr_still_rejects_foreign_invalid_scientific_or_original_identity(
        self,
    ):
        payload = {"metadata": caches.build_cache_metadata(str(self.pdf))}
        for field, value in (
            ("product", {"name": "Foreign", "version": "0.1.0"}),
            ("product", {"name": core.PRODUCT_NAME, "version": "0.1.100"}),
            ("pdf_sha256", "0" * 64),
            (
                "pipeline_contract",
                {"name": core.PIPELINE_CONTRACT_NAME, "version": "999"},
            ),
            ("ruleset", {"name": core.RULESET_NAME, "version": "999"}),
            ("schema", {"name": core.PAGE_OCR_CACHE_SCHEMA, "version": 999}),
        ):
            candidate = copy.deepcopy(payload)
            candidate["metadata"][field] = value
            with self.subTest(field=field):
                self.assertFalse(caches.cache_matches_pdf(candidate, str(self.pdf)))

    def test_segment_input_keeps_every_field_exact_except_valid_producer_release(self):
        with patch.object(core, "__version__", "0.1.0"):
            spec, source, root, _plan, jobs, fingerprints = (
                segment_cases.SegmentationCheckpointTests.plan(self)
            )
        input_file = Path(jobs[0]["fingerprint_file"])
        original = input_file.read_bytes()
        locator = source / "structure_pages/locator.json"
        locator_before = locator.read_bytes()
        with patch.object(core, "__version__", "1.0.0"):
            verified = verified_input(
                spec.pdf_path, root, Path(jobs[0]["output"]), [0], str(input_file), ""
            )
            self.assertEqual(verified["product"]["version"], "1.0.0")
            for field, value in (
                ("pdf_sha256", "0" * 64),
                ("product", {"name": "Foreign", "version": "0.1.0"}),
                ("params_digest", "0" * 64),
                ("extra", "unproved"),
            ):
                write_json_atomic(input_file, {**fingerprints[0], field: value})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    verified_input(
                        spec.pdf_path,
                        root,
                        Path(jobs[0]["output"]),
                        [0],
                        str(input_file),
                        "",
                    )
            write_json_atomic(input_file, fingerprints[0])
        self.assertEqual(input_file.read_bytes(), original)
        self.assertEqual(locator.read_bytes(), locator_before)


if __name__ == "__main__":
    unittest.main()
