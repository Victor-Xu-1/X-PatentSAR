"""Older native/raster cache refusal and unchanged raw-scope transport."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_hybrid_source_native import hybrid_page

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core import page_ocr_cache as cache_module


class HybridSourceCacheTests(unittest.TestCase):
    def test_legacy_footer_only_observations_are_not_current_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            pdf = Path(root) / "original.pdf"
            doc, _page = hybrid_page()
            with doc:
                doc.save(pdf)
            metadata = cache_module.build_cache_metadata(str(pdf))
            metadata["observation_contract"]["version"] = 1
            payload = {
                "metadata": metadata,
                "page_texts": {"1": "Original footer only"},
                "ocr_line_map": {},
            }
            source = Path(root) / "historical.json"
            write_json_atomic(source, payload)
            before = source.read_bytes()
            with patch.object(
                cache_module,
                "get_ocr_engine",
                side_effect=AssertionError(
                    "Compatibility is read-only original metadata"
                ),
            ):
                self.assertFalse(cache_module.cache_matches_pdf(payload, str(pdf)))
                with self.assertRaises(ValueError):
                    cache_module.inherit_page_ocr_cache(
                        str(source), str(Path(root) / "new.json"), str(pdf)
                    )
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse((Path(root) / "new.json").exists())

    def test_unchanged_legacy_native_page_transport_keeps_source_bytes_and_receipt(
        self,
    ):
        with tempfile.TemporaryDirectory() as root:
            pdf = Path(root) / "original.pdf"
            doc, _page = hybrid_page()
            with doc:
                doc.save(pdf)
            metadata = cache_module.build_cache_metadata(str(pdf))
            metadata["observation_contract"]["version"] = 1
            payload = {
                "metadata": metadata,
                "page_texts": {"0": "Original native table"},
                "ocr_line_map": {},
            }
            source, target = Path(root) / "historical.json", Path(root) / "new.json"
            write_json_atomic(source, payload)
            before = source.read_bytes()
            with patch.object(
                cache_module,
                "get_ocr_engine",
                side_effect=AssertionError("Unchanged original needs no re-inference"),
            ):
                self.assertTrue(cache_module.cache_matches_pdf(payload, str(pdf)))
                self.assertTrue(
                    cache_module.inherit_page_ocr_cache(
                        str(source), str(target), str(pdf)
                    )
                )
                current = cache_module.update_page_ocr_cache(str(pdf), [0], str(target))
                repeated = cache_module.update_page_ocr_cache(
                    str(pdf), [0], str(target)
                )
                self.assertEqual(
                    repeated["metadata"]["source_policy_validation"],
                    current["metadata"]["source_policy_validation"],
                )
            self.assertEqual(current["page_texts"], payload["page_texts"])
            self.assertEqual(
                current["metadata"]["inherited_observation_contract"]["version"], 1
            )
            self.assertEqual(
                current["metadata"]["source_policy_validation"]["checked_pages"], [0]
            )
            self.assertEqual(
                json.loads(target.read_text())["metadata"][
                    "inherited_observation_contract"
                ]["version"],
                1,
            )
            self.assertEqual(source.read_bytes(), before)
