from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.core import page_ocr_cache as caches


class OCRCacheInheritanceTests(unittest.TestCase):
    def fixture(self, root):
        pdf = root / "input.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text(
                (70, 80), "Known native content for original PDF verification"
            )
            doc.save(pdf)
        metadata = caches.build_cache_metadata(str(pdf))
        metadata["ruleset"]["version"] = "2.0.1"
        metadata.pop("observation_contract")
        source = root / "prior" / "page_ocr_cache.json"
        write_json_atomic(
            source,
            {
                "metadata": metadata,
                "page_texts": {"0": "Verified original observation"},
                "ocr_line_map": {"0": [{"y0": 80, "text": "Observed evidence"}]},
            },
        )
        return pdf, source

    def test_verified_raw_observations_are_reused_without_promoting_old_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, source = self.fixture(root)
            before = source.read_bytes()
            target = root / "new" / "page_ocr_cache.json"
            self.assertTrue(
                caches.inherit_page_ocr_cache(str(source), str(target), str(pdf))
            )
            with patch.object(
                caches, "get_ocr_engine", side_effect=AssertionError("No duplicate OCR")
            ):
                actual = caches.update_page_ocr_cache(str(pdf), [0], str(target))
            self.assertEqual(actual["page_texts"]["0"], "Verified original observation")
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(
                artifact_identity_matches(
                    actual["metadata"], ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION
                )
            )
            self.assertFalse(
                caches.inherit_page_ocr_cache(str(source), str(target), str(pdf))
            )

    def test_incoherent_legacy_cache_wrong_original_and_observation_revision_are_rejected(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, source = self.fixture(root)
            base = caches.load_page_ocr_cache(str(source))
            for field, value in (
                ("ruleset", {"name": "patentsar.accuracy-first", "version": "2.0.0"}),
                ("pdf_sha256", "0" * 64),
                (
                    "observation_contract",
                    {"name": "patentsar.page-ocr-observation", "version": 999},
                ),
                ("page_count", True),
            ):
                candidate = {**base, "metadata": {**base["metadata"], field: value}}
                write_json_atomic(source, candidate)
                target = root / "rejected" / "cache.json"
                with self.subTest(field=field), self.assertRaises(ValueError):
                    caches.inherit_page_ocr_cache(str(source), str(target), str(pdf))
                self.assertFalse(target.exists())
