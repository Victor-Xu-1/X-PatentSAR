"""Complete shared original observations replace private binder OCR workers."""

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import binding_page_source as source
from patent_sar_extractor.core.binding_preparation import prepare_binding_observations
from patent_sar_extractor.core.page_ocr_cache import (
    build_cache_metadata,
    update_page_ocr_cache,
)
from patent_sar_extractor.core.page_ocr_execution import PageObservationError
from patent_sar_extractor.core.source_geometry import native_lines, source_layout


class BindingPageSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="binding-original-pages-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = self.root / "original.pdf"
        with fitz.open() as document:
            document.new_page().insert_text((60, 75), "Compound 41A: Preparation")
            document.new_page().insert_text((60, 75), "Compound 78B: Preparation")
            document.save(self.original)
        self.cache_path = self.root / "source.json"

    def load(self, *, profile_lines=None):
        with fitz.open(self.original) as document:
            return source.binding_page_source(
                document, str(self.original), self.cache_path, 1, profile_lines or {}
            )

    def test_missing_cache_observes_every_page_once_and_native_reuse_needs_no_model(
        self,
    ):
        with (
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Native source needs no model"),
            ),
            patch.object(
                source, "update_page_ocr_cache", wraps=update_page_ocr_cache
            ) as update,
        ):
            cache, lines = self.load()
            before = self.cache_path.read_bytes()
            reused, repeated = self.load()
        self.assertEqual(update.call_count, 1)
        self.assertEqual(update.call_args.args[1], [0, 1])
        self.assertEqual(cache, reused)
        self.assertEqual(lines, repeated)
        self.assertEqual(self.cache_path.read_bytes(), before)
        self.assertEqual(set(lines), {0, 1})
        self.assertTrue(
            all(
                row["source"] == "native" and row["bbox"]
                for page in lines.values()
                for row in page
            )
        )

    def test_original_native_coordinate_projection_does_not_rewrite_saved_raw_data(
        self,
    ):
        self.load()
        cache = json.loads(self.cache_path.read_text())
        cache["ocr_line_map"].pop("1", None)
        self.cache_path.write_text(json.dumps(cache))
        before = self.cache_path.read_bytes()
        with patch.object(
            source,
            "update_page_ocr_cache",
            side_effect=AssertionError("No source replay"),
        ):
            _, lines = self.load()
        self.assertEqual(lines[1][0]["text"], "Compound 78B: Preparation")
        self.assertEqual(lines[1][0]["source"], "native")
        self.assertEqual(self.cache_path.read_bytes(), before)

    def test_corrupt_foreign_or_incomplete_saved_source_is_never_rebuilt(self):
        original, _ = self.load()
        for mutation in ("foreign", "incomplete", "empty_native", "empty_with_lines"):
            cache = json.loads(json.dumps(original))
            if mutation == "foreign":
                cache["metadata"]["pdf_sha256"] = "0" * 64
            elif mutation == "incomplete":
                cache["page_texts"].pop("1")
                cache["ocr_line_map"].pop("1", None)
            else:
                cache["page_texts"]["1"] = ""
                cache["ocr_line_map"].pop("1", None)
                if mutation == "empty_with_lines":
                    cache["ocr_line_map"]["1"] = [
                        {"y0": 60, "text": "Original observed title"}
                    ]
            self.cache_path.write_text(json.dumps(cache))
            before = self.cache_path.read_bytes()
            with (
                self.subTest(mutation=mutation),
                patch.object(
                    source,
                    "update_page_ocr_cache",
                    side_effect=AssertionError("Cannot rewrite old raw evidence"),
                ),
                self.assertRaises((ValueError, PageObservationError)),
            ):
                self.load()
            self.assertEqual(self.cache_path.read_bytes(), before)

    def test_scan_text_without_coordinates_cannot_be_silently_empty_or_fabricated(self):
        with fitz.open(self.original) as native, fitz.open() as document:
            pixels = native[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            page = document.new_page()
            page.insert_image(page.rect, stream=pixels.tobytes("png"))
            raster = self.root / "raster.pdf"
            document.save(raster)
        cache = {
            "metadata": build_cache_metadata(str(raster)),
            "page_texts": {"0": "Compound 41A: Preparation"},
            "ocr_line_map": {},
        }
        self.cache_path.write_text(json.dumps(cache))
        before = self.cache_path.read_bytes()
        with (
            fitz.open(raster) as document,
            patch.object(
                source,
                "update_page_ocr_cache",
                side_effect=AssertionError("Do not overwrite raw source"),
            ),
            self.assertRaisesRegex(PageObservationError, "source coordinates"),
        ):
            source.binding_page_source(document, str(raster), self.cache_path, 1, {})
        self.assertEqual(self.cache_path.read_bytes(), before)

    def test_shared_observer_failure_cannot_become_a_successful_empty_page(self):
        with (
            patch.object(
                source,
                "update_page_ocr_cache",
                side_effect=PageObservationError("Controlled source failure"),
            ) as update,
            self.assertRaisesRegex(PageObservationError, "Controlled source failure"),
        ):
            self.load()
        self.assertEqual(update.call_count, 1)
        self.assertFalse(self.cache_path.exists())

    def test_partial_shared_failure_keeps_completed_original_checkpoint_without_acceptance(
        self,
    ):
        with fitz.open(self.original) as document:
            text = document[0].get_text("text")
            lines = native_lines(source_layout(document[0]))

        def observed(*args, **kwargs):
            yield 0, text, lines
            raise PageObservationError("Controlled second-page failure")

        with (
            patch(
                "patent_sar_extractor.core.page_ocr_cache._page_observations",
                side_effect=observed,
            ),
            self.assertRaisesRegex(PageObservationError, "second-page failure"),
        ):
            self.load()
        cache = json.loads(self.cache_path.read_text())
        self.assertEqual(set(cache["page_texts"]), {"0"})
        self.assertEqual(cache["ocr_line_map"]["0"], lines)
        before = self.cache_path.read_bytes()
        with (
            patch.object(
                source,
                "update_page_ocr_cache",
                side_effect=AssertionError("Saved partial source remains immutable"),
            ),
            self.assertRaises(ValueError),
        ):
            self.load()
        self.assertEqual(self.cache_path.read_bytes(), before)

    def test_profile_hints_do_not_replace_original_lines_or_manufacture_geometry(self):
        cache, lines = self.load(profile_lines={0: [(70, "Compound 999")]})
        self.assertEqual(cache["page_texts"]["0"].strip(), "Compound 41A: Preparation")
        self.assertTrue(
            any(
                row["text"] == "Compound 41A: Preparation" and row.get("bbox")
                for row in lines[0]
            )
        )
        self.assertEqual(
            [row for row in lines[0] if row["text"] == "Compound 999"],
            [{"y0": 70, "text": "Compound 999"}],
        )

    def test_non_candidate_pages_still_supply_complete_original_heading_observations(
        self,
    ):
        with fitz.open(self.original) as document:
            result = prepare_binding_observations(
                document,
                str(self.original),
                {
                    "ocr_cache_path": str(self.cache_path),
                    "structure_candidate_pages": [0],
                },
                self.root / "binding",
                [],
            )
        self.assertEqual(result.page_indices, [0])
        self.assertEqual(set(result.pages_text), {0, 1})
        self.assertEqual(
            result.source_line_map[1][0]["text"], "Compound 78B: Preparation"
        )

    def test_private_binder_ocr_and_parallel_execution_are_removed_not_competing(self):
        core = Path(source.__file__).parent
        self.assertFalse((core / "binding_ocr.py").exists())
        tree = ast.parse((core / "binding_preparation.py").read_text())
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertTrue(
            {
                "ThreadPoolExecutor",
                "as_completed",
                "_worker_observation",
                "page_text",
            }.isdisjoint(names)
        )


if __name__ == "__main__":
    unittest.main()
