"""Binder adapters consume the shared OCR authority; no private providers."""

from __future__ import annotations

import ast
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core import binding_ocr, page_ocr_cache


class BindingSharedOCRTests(unittest.TestCase):
    def test_private_binding_provider_and_crop_producer_are_absent(self):
        from patent_sar_extractor.core import binding_observations

        for name in (
            "_PADDLEX_OCR_AVAILABLE",
            "_get_ocr_word_coords",
            "_paddlex_ocr_url",
            "_paddlex_ocr_texts_from_image",
            "_paddlex_ocr_texts_batch",
            "_allow_tesseract_fallback",
            "paddlex_available",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(binding_ocr, name))
        self.assertFalse(
            hasattr(binding_observations, "_precompute_visible_label_cache")
        )
        core = Path(binding_ocr.__file__).parent
        self.assertFalse((core / "visible_label_crops.py").exists())
        tree = ast.parse(Path(binding_ocr.__file__).read_text())
        imports = {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertTrue(
            imports.isdisjoint(
                {"rapidocr_onnxruntime", "pytesseract", "requests", "subprocess"}
            )
        )

    def test_short_native_lines_are_lazy_and_keep_original_coordinates(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((80, 150), "Example 7B", fontsize=10)
            expected = page.get_text("dict")["blocks"][0]["lines"][0]["bbox"][1]
            with (
                patch.object(
                    page_ocr_cache,
                    "get_ocr_engine",
                    side_effect=AssertionError("Native page needs no engine"),
                ) as shared,
                patch(
                    "rapidocr_onnxruntime.RapidOCR",
                    side_effect=AssertionError("No private engine"),
                ) as private,
            ):
                lines = binding_ocr._get_ocr_line_coords(page)
            self.assertEqual(lines, [(expected, "Example 7B")])
            shared.assert_not_called()
            private.assert_not_called()

    def test_scanned_coordinates_use_one_shared_inference_and_pdf_units(self):
        backend = Mock(
            return_value=(
                [
                    ([[0, 100], [100, 100], [100, 120], [0, 120]], "Example 7B", 0.99),
                    ([[0, 150], [100, 150], [100, 170], [0, 170]], "  ", 0.99),
                ],
                None,
            )
        )
        with fitz.open() as doc:
            page = doc.new_page()
            with patch.object(
                page_ocr_cache, "get_ocr_engine", return_value=("rapidocr", backend)
            ) as shared:
                result = binding_ocr._get_ocr_line_coords(page)
        self.assertEqual(result, [(48.0, "Example 7B")])
        shared.assert_called_once()
        backend.assert_called_once()

    def test_empty_shared_result_does_not_start_private_ocr(self):
        backend = Mock(return_value=([], None))
        with fitz.open() as doc:
            page = doc.new_page()
            with (
                patch.object(
                    page_ocr_cache, "get_ocr_engine", return_value=("rapidocr", backend)
                ),
                patch(
                    "rapidocr_onnxruntime.RapidOCR",
                    side_effect=AssertionError("No retry provider"),
                ) as private,
                patch.dict("os.environ", {"WIPO_ALLOW_TESSERACT_FALLBACK": "off"}),
            ):
                self.assertEqual(binding_ocr._get_ocr_line_coords(page), [])
            private.assert_not_called()
        backend.assert_called_once()

    def test_unavailable_or_text_only_shared_engine_is_not_coordinate_evidence(self):
        for engine in (False, ("tesseract", Mock()), ("tesseract_cli", "unused")):
            with self.subTest(engine=engine), fitz.open() as doc:
                with (
                    patch.object(page_ocr_cache, "get_ocr_engine", return_value=engine),
                    patch(
                        "rapidocr_onnxruntime.RapidOCR",
                        side_effect=AssertionError("No parallel provider"),
                    ) as private,
                    patch.dict("os.environ", {"WIPO_ALLOW_TESSERACT_FALLBACK": "off"}),
                ):
                    self.assertEqual(
                        binding_ocr._get_ocr_line_coords(doc.new_page()), []
                    )
                private.assert_not_called()

    def test_shared_failure_is_not_silently_replaced_by_another_provider(self):
        with fitz.open() as doc:
            with (
                patch.object(
                    page_ocr_cache, "get_ocr_engine", return_value=("rapidocr", Mock())
                ),
                patch.object(
                    page_ocr_cache,
                    "page_ocr_lines",
                    side_effect=RuntimeError("shared OCR failed"),
                ),
                patch(
                    "rapidocr_onnxruntime.RapidOCR",
                    side_effect=AssertionError("No private retry"),
                ) as private,
                self.assertRaisesRegex(RuntimeError, "shared OCR failed"),
            ):
                binding_ocr._get_ocr_line_coords(doc.new_page())
            private.assert_not_called()

    def test_bad_shared_coordinates_are_not_fabricated_at_page_origin(self):
        for row in (
            {"text": "Example 7B"},
            {"y0": float("nan"), "text": "Example 7B"},
            {"y0": True, "text": "Example 7B"},
        ):
            with (
                self.subTest(row=row),
                fitz.open() as doc,
                patch.object(
                    page_ocr_cache,
                    "get_ocr_engine",
                    return_value=("rapidocr", Mock()),
                ),
                patch.object(page_ocr_cache, "page_ocr_lines", return_value=[row]),
                patch(
                    "rapidocr_onnxruntime.RapidOCR",
                    side_effect=AssertionError("No private retry"),
                ),
                self.assertRaises(ValueError),
            ):
                binding_ocr._get_ocr_line_coords(doc.new_page())

    def test_shared_paddlex_coordinates_use_one_payload_not_a_binder_provider(self):
        with (
            fitz.open() as doc,
            patch.object(
                page_ocr_cache, "get_ocr_engine", return_value=("paddlex", None)
            ),
            patch.object(
                page_ocr_cache,
                "_paddlex_payload_from_image",
                return_value=(["Example 9C"], [[0, 100, 100, 120]]),
            ) as payload,
        ):
            self.assertEqual(
                binding_ocr._get_ocr_line_coords(doc.new_page()), [(48.0, "Example 9C")]
            )
        payload.assert_called_once()

    def test_nontext_shared_observation_is_rejected_without_private_retry(self):
        with (
            fitz.open() as doc,
            patch.object(
                page_ocr_cache, "get_ocr_engine", return_value=("rapidocr", Mock())
            ),
            patch.object(
                page_ocr_cache,
                "page_ocr_lines",
                return_value=[{"y0": 48.0, "text": 17}],
            ),
            self.assertRaises(TypeError),
        ):
            binding_ocr._get_ocr_line_coords(doc.new_page())

    def test_workers_reopen_native_pdf_without_loading_models(self):
        with tempfile.TemporaryDirectory(prefix="binding-shared-ocr-") as temporary:
            pdf = Path(temporary) / "native.pdf"
            with fitz.open() as doc:
                for label in ("Example 7B", "Example 8A"):
                    doc.new_page().insert_text((70, 80), label)
                doc.save(pdf)
            with (
                patch.object(
                    page_ocr_cache,
                    "get_ocr_engine",
                    side_effect=AssertionError("No native model startup"),
                ) as shared,
                patch(
                    "rapidocr_onnxruntime.RapidOCR",
                    side_effect=AssertionError("No private engine"),
                ) as private,
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                rows = list(
                    pool.map(
                        lambda index: binding_ocr._extract_binder_page_lines(
                            str(pdf), index
                        ),
                        (0, 1),
                    )
                )
                text = binding_ocr._extract_binder_page_text(str(pdf), 0)
            self.assertEqual([row[0] for row in rows], [0, 1])
            self.assertEqual(
                [row[1][0][1] for row in rows], ["Example 7B", "Example 8A"]
            )
            self.assertEqual(text, (0, "Example 7B\n"))
            shared.assert_not_called()
            private.assert_not_called()

    def test_scanned_text_worker_delegates_to_shared_page_text(self):
        with tempfile.TemporaryDirectory(prefix="binding-shared-text-") as temporary:
            pdf = Path(temporary) / "scanned.pdf"
            with fitz.open() as doc:
                doc.new_page()
                doc.save(pdf)
            backend = Mock(
                return_value=(
                    [
                        (
                            [[0, 100], [100, 100], [100, 120], [0, 120]],
                            "Example 7B",
                            0.99,
                        ),
                    ],
                    None,
                )
            )
            with patch.object(
                page_ocr_cache, "get_ocr_engine", return_value=("rapidocr", backend)
            ):
                self.assertEqual(
                    binding_ocr._extract_binder_page_text(str(pdf), 0),
                    (0, "Example 7B"),
                )
            backend.assert_called_once()

    def test_worker_failure_closes_document_and_does_not_return_empty_success(self):
        for helper, failing_name in (
            (binding_ocr._extract_binder_page_text, "page_text"),
            (binding_ocr._extract_binder_page_lines, "page_ocr_lines"),
        ):
            with self.subTest(helper=helper.__name__):
                page = Mock()
                page.get_text.side_effect = lambda kind: (
                    {"blocks": []} if kind == "dict" else ""
                )
                document = Mock()
                document.__getitem__ = Mock(return_value=page)
                with (
                    patch.object(binding_ocr.fitz, "open", return_value=document),
                    patch.object(
                        page_ocr_cache,
                        "get_ocr_engine",
                        return_value=("rapidocr", Mock()),
                    ),
                    patch.object(
                        page_ocr_cache,
                        failing_name,
                        side_effect=RuntimeError("shared worker failure"),
                    ),
                    patch(
                        "rapidocr_onnxruntime.RapidOCR",
                        side_effect=AssertionError("No private retry"),
                    ),
                    self.assertRaisesRegex(RuntimeError, "shared worker failure"),
                ):
                    helper("controlled.pdf", 0)
                document.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
