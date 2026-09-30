from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core import page_ocr_cache as cache_module


class PageOCRPayloadTests(unittest.TestCase):
    def _pdf(self, path: Path, text: str = "") -> None:
        with fitz.open() as document:
            for _ in range(2):
                page = document.new_page()
                if text:
                    page.insert_text((72, 72), text)
            document.save(path)

    def _cache(self, pdf: Path, output: Path, mode: str, workers: int):
        if mode == "build":
            return cache_module.build_page_ocr_cache(str(pdf), [0, 1], workers=workers)
        return cache_module.update_page_ocr_cache(
            str(pdf), [0, 1], str(output), workers=workers
        )

    def test_scanned_rapidocr_always_saves_coordinates_with_one_inference_per_page(
        self,
    ):
        rows = [
            (
                [
                    [0, 100 + index * 40],
                    [100, 100 + index * 40],
                    [100, 120 + index * 40],
                    [0, 120 + index * 40],
                ],
                f"I-{index + 1} structure label evidence",
                0.99,
            )
            for index in range(6)
        ]
        for mode in ("build", "update"):
            for workers in (1, 2):
                with (
                    self.subTest(mode=mode, workers=workers),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    pdf = root / "scanned.pdf"
                    self._pdf(pdf)
                    backend = Mock(return_value=(rows, None))
                    with (
                        patch.object(
                            cache_module,
                            "get_ocr_engine",
                            return_value=("rapidocr", backend),
                        ),
                        patch.object(
                            cache_module,
                            "_build_ocr_engine",
                            return_value=("rapidocr", backend),
                        ),
                        patch.object(cache_module, "_THREAD_OCR", threading.local()),
                    ):
                        result = self._cache(pdf, root / "cache.json", mode, workers)
                    for index in (0, 1):
                        lines = result["ocr_line_map"].get(str(index), [])
                        self.assertEqual(len(lines), 6)
                        self.assertEqual(lines[0]["y0"], 48.0)
                        self.assertEqual(
                            result["page_texts"][str(index)],
                            " ".join(line["text"] for line in lines),
                        )
                    self.assertEqual(
                        backend.call_count,
                        2,
                        "OCR text and coordinates must share one inference",
                    )

    def test_native_text_does_not_construct_an_ocr_engine_in_any_cache_path(self):
        for mode in ("build", "update"):
            for workers in (1, 2):
                with (
                    self.subTest(mode=mode, workers=workers),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    pdf = root / "native.pdf"
                    self._pdf(pdf, "Native patent text " * 5)
                    with (
                        patch.object(
                            cache_module,
                            "get_ocr_engine",
                            side_effect=AssertionError("No OCR needed"),
                        ),
                        patch.object(
                            cache_module,
                            "_build_ocr_engine",
                            side_effect=AssertionError("No OCR needed"),
                        ),
                    ):
                        result = self._cache(pdf, root / "cache.json", mode, workers)
                    self.assertEqual(len(result["page_texts"]), 2)
                    self.assertEqual(result["ocr_line_map"], {})

    def test_empty_ocr_preserves_short_native_text_without_duplicate_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "partial-native.pdf"
            self._pdf(pdf, "abc")
            backend = Mock(return_value=([], None))
            with patch.object(
                cache_module, "get_ocr_engine", return_value=("rapidocr", backend)
            ):
                result = cache_module.build_page_ocr_cache(str(pdf), [0], workers=1)
            self.assertEqual(result["page_texts"]["0"], "abc")
            self.assertEqual(result["ocr_line_map"], {})
            self.assertEqual(backend.call_count, 1)

    def test_paddlex_text_and_coordinates_share_one_request_per_page(self):
        for workers in (1, 2):
            with (
                self.subTest(workers=workers),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                pdf = root / "paddlex.pdf"
                self._pdf(pdf)
                payload = Mock(
                    return_value=(
                        ["I-1 complete structure table evidence"],
                        [[0, 100, 100, 120]],
                    )
                )
                with (
                    patch.object(
                        cache_module, "get_ocr_engine", return_value=("paddlex", None)
                    ),
                    patch.object(
                        cache_module,
                        "_build_ocr_engine",
                        return_value=("paddlex", None),
                    ),
                    patch.object(cache_module, "_paddlex_payload_from_image", payload),
                    patch.object(cache_module, "_THREAD_OCR", threading.local()),
                ):
                    result = self._cache(pdf, root / "cache.json", "update", workers)
                self.assertEqual(payload.call_count, 2)
                self.assertEqual(result["ocr_line_map"]["0"][0]["y0"], 48.0)
                self.assertEqual(
                    result["page_texts"]["0"], result["ocr_line_map"]["0"][0]["text"]
                )


if __name__ == "__main__":
    unittest.main()
