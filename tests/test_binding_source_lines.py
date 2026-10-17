"""Binding cannot discard, overwrite or fabricate original source line geometry."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_preparation import prepare_binding_observations
from patent_sar_extractor.core.binding_source_lines import (
    merged_source_lines,
    source_line_map,
)
from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata


class BindingSourceLineTests(unittest.TestCase):
    def fixture(self, root):
        original = root / "original.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text((60, 75), "Compound 41A: Preparation")
            doc.new_page().insert_text((60, 90), "Compound No. Structure")
            doc.save(original)
        cache = {
            "metadata": build_cache_metadata(str(original)),
            "page_texts": {
                "0": "Compound 41A: Preparation",
                "1": "Compound No. Structure",
            },
            "ocr_line_map": {
                "0": [
                    {
                        "y0": 63.1,
                        "text": "Compound 41A: Preparation",
                        "bbox": [60.0, 63.1, 230.0, 78.2],
                        "source": "page_ocr",
                        "geometry_space": "rendered",
                    }
                ]
            },
        }
        path = root / "page_ocr_cache.json"
        path.write_text(json.dumps(cache), encoding="utf-8")
        return original, path, cache

    def test_preparation_keeps_rich_lines_and_legacy_projection_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, path, cache = self.fixture(root)
            with fitz.open(original) as doc:
                result = prepare_binding_observations(
                    doc,
                    str(original),
                    {"ocr_cache_path": str(path), "structure_candidate_pages": [0]},
                    root / "binding",
                    [],
                )
            self.assertEqual(result.source_line_map[0], cache["ocr_line_map"]["0"])
            self.assertEqual(result.line_map[0], [(63.1, "Compound 41A: Preparation")])

    def test_a_missing_page_checkpoint_does_not_strip_existing_raw_boxes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, path, cache = self.fixture(root)
            with fitz.open(original) as doc:
                prepare_binding_observations(
                    doc,
                    str(original),
                    {
                        "ocr_cache_path": str(path),
                        "structure_candidate_pages": [0, 1],
                        "authoritative_structure_table_pages": [1],
                    },
                    root / "binding",
                    [],
                )
            saved = json.loads(path.read_text())
            self.assertEqual(saved["ocr_line_map"]["0"], cache["ocr_line_map"]["0"])
            self.assertEqual(saved["metadata"], cache["metadata"])

    def test_foreign_cache_cannot_supply_or_overwrite_original_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, path, cache = self.fixture(root)
            cache["metadata"]["pdf_sha256"] = "0" * 64
            path.write_text(json.dumps(cache), encoding="utf-8")
            before = path.read_bytes()
            with fitz.open(original) as doc, self.assertRaises(ValueError):
                prepare_binding_observations(
                    doc,
                    str(original),
                    {"ocr_cache_path": str(path)},
                    root / "binding",
                    [],
                )
            self.assertEqual(path.read_bytes(), before)

    def test_profile_locators_cannot_manufacture_rich_original_evidence(self):
        raw = {
            "y0": 63.1,
            "text": "Compound 41A: Preparation",
            "bbox": [60.0, 63.1, 230.0, 78.2],
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        self.assertNotIn("bbox", merged_source_lines({0: [raw]}, {})[0][0])
        self.assertEqual(merged_source_lines({0: [raw]}, {"0": [raw]})[0], [raw])

    def test_duplicate_normalized_page_keys_do_not_erase_observations(self):
        with self.assertRaises(ValueError):
            source_line_map({0: [(60, "Compound 41")], "0": [(70, "Compound 42")]})

    def test_incomplete_or_unlocated_original_source_is_not_an_empty_page(self):
        for phase in ("missing_page", "unlocated_text"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original, path, cache = self.fixture(root)
                cache["ocr_line_map"] = {}
                if phase == "missing_page":
                    cache["page_texts"] = {}
                else:
                    cache["page_texts"]["0"] = "Unlocated original text"
                path.write_text(json.dumps(cache), encoding="utf-8")
                before = path.read_bytes()
                with (
                    fitz.open(original) as doc,
                    patch(
                        "patent_sar_extractor.core.binding_page_source.update_page_ocr_cache",
                        side_effect=AssertionError(
                            "Saved source cannot be overwritten"
                        ),
                    ),
                    self.assertRaises((ValueError, RuntimeError)),
                ):
                    prepare_binding_observations(
                        doc,
                        str(original),
                        {"ocr_cache_path": str(path), "bind_workers": 2},
                        root / "binding",
                        [],
                    )
                self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
