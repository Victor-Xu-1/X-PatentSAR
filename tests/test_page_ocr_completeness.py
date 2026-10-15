"""Whole-page source failures cannot become successful partial classification."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fitz
import requests
from PIL import Image

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core import page_classifier
from patent_sar_extractor.core import page_ocr_cache as caches


class PageOCRCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ocr-complete-control-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pdf = self.root / "original.pdf"
        with fitz.open() as document:
            for index in range(3):
                page = document.new_page()
                page.insert_text(
                    (40, 80),
                    f"Original native page {index}; Compound synthesis IC50 assay information",
                )
            document.save(self.pdf)

    def test_parallel_wrong_page_never_enters_build_or_checkpoint(self):
        for mode in ("build", "update"):
            with (
                self.subTest(mode=mode),
                patch.object(
                    caches,
                    "_extract_page_payload",
                    side_effect=lambda pdf, idx, minimum: (idx + 1, "Foreign page", []),
                ),
                self.assertRaises((RuntimeError, ValueError)),
            ):
                if mode == "build":
                    caches.build_page_ocr_cache(str(self.pdf), [0, 1, 2], workers=2)
                else:
                    caches.update_page_ocr_cache(
                        str(self.pdf),
                        [0, 1, 2],
                        str(self.root / "wrong.json"),
                        workers=2,
                        retry_empty=False,
                    )

    def test_unavailable_page_fails_and_preserves_completed_original_checkpoint(self):
        ready = threading.Event()

        def observe(pdf, idx, minimum):
            if idx == 0:
                ready.set()
                return idx, "Owned original page zero", []
            if idx == 1:
                self.assertTrue(ready.wait(1))
                time.sleep(0.03)
                raise RuntimeError("Controlled source observation unavailable")
            return idx, "Owned original page two", []

        target = self.root / "partial.json"
        with (
            patch.object(caches, "_extract_page_payload", side_effect=observe),
            self.assertRaises(RuntimeError),
        ):
            caches.update_page_ocr_cache(
                str(self.pdf),
                [0, 1, 2],
                str(target),
                workers=2,
                flush_every=50,
                retry_empty=False,
            )
        saved = json.loads(target.read_text())
        self.assertEqual(saved["page_texts"]["0"], "Owned original page zero")
        self.assertNotIn("1", saved["page_texts"])

    def test_cached_nontext_and_foreign_page_are_not_native_observations(self):
        for values in (
            {"0": True},
            {"9": "Foreign page"},
            {"01": "Ambiguous page spelling"},
        ):
            target = self.root / "malformed.json"
            write_json_atomic(
                target,
                {
                    "metadata": caches.build_cache_metadata(str(self.pdf)),
                    "page_texts": values,
                    "ocr_line_map": {},
                },
            )
            before = target.read_bytes()
            with (
                self.subTest(values=values),
                patch.object(
                    caches,
                    "get_ocr_engine",
                    side_effect=AssertionError(
                        "Never repair original cache with invented observations"
                    ),
                ),
                self.assertRaises((RuntimeError, ValueError)),
            ):
                caches.update_page_ocr_cache(
                    str(self.pdf), [0], str(target), retry_empty=False
                )
            self.assertEqual(target.read_bytes(), before)

    def test_classifier_refuses_missing_page_source_instead_of_claiming_full_pdf(self):
        packet = {
            "metadata": caches.build_cache_metadata(str(self.pdf)),
            "page_texts": {"0": "Original Compound IC50 information"},
            "ocr_line_map": {},
        }
        output = self.root / "classification"
        with (
            patch.object(page_classifier, "update_page_ocr_cache", return_value=packet),
            self.assertRaises((RuntimeError, ValueError)),
        ):
            page_classifier.classify_pdf(str(self.pdf), str(output))
        self.assertFalse((output / "page_classification.json").exists())

    def test_unobserved_raster_without_engine_cannot_be_blank_native_success(self):
        page = Mock()
        page.get_text.return_value = ""
        layout = SimpleNamespace(native=(), raster_bounds=fitz.Rect(0, 0, 100, 100))
        with (
            patch.object(caches, "source_layout", return_value=layout),
            self.assertRaises(RuntimeError),
        ):
            caches._page_payload(page, ocr_engine=False)

    def _response(self, payload):
        response = Mock()
        response.json.return_value = payload
        return patch("requests.Session.post", return_value=response)

    def test_paddlex_timeout_is_not_empty_observation_or_native_fallback(self):
        with (
            patch.object(
                caches, "_paddlex_ocr_url", return_value="http://127.0.0.1:1/ocr"
            ),
            patch(
                "requests.Session.post",
                side_effect=requests.Timeout("Controlled timeout"),
            ),
            self.assertRaises(RuntimeError),
        ):
            caches._paddlex_payload_from_image(Image.new("RGB", (5, 5)))

    def test_paddlex_missing_ambiguous_or_truncated_response_is_not_partial_success(
        self,
    ):
        good = {
            "prunedResult": {"rec_texts": ["Compound 11"], "rec_boxes": [[0, 0, 5, 5]]}
        }
        bad = {
            "prunedResult": {
                "rec_texts": ["Compound 11", "Compound 12"],
                "rec_boxes": [[0, 0, 5, 5]],
            }
        }
        for payload in (
            {},
            {"result": {"ocrResults": [bad]}},
            {"result": {"ocrResults": [good, good]}},
        ):
            with (
                self.subTest(payload=payload),
                patch.object(
                    caches, "_paddlex_ocr_url", return_value="http://127.0.0.1:1/ocr"
                ),
                self._response(payload),
                self.assertRaises(RuntimeError),
            ):
                caches._paddlex_payload_from_image(Image.new("RGB", (5, 5)))

    def test_real_native_pages_stay_complete_without_model_initialization(self):
        with (
            patch.object(
                caches, "get_ocr_engine", side_effect=AssertionError("Native fast path")
            ),
            patch.object(
                caches,
                "_build_ocr_engine",
                side_effect=AssertionError("Native fast path"),
            ),
        ):
            for workers in (1, 2):
                value = caches.update_page_ocr_cache(
                    str(self.pdf),
                    [0, 1, 2],
                    str(self.root / f"native-{workers}.json"),
                    workers=workers,
                )
                self.assertEqual(set(value["page_texts"]), {"0", "1", "2"})
                self.assertEqual(value["ocr_line_map"], {})

    def test_valid_empty_paddlex_observation_is_not_a_transport_failure(self):
        for observations in (
            [],
            [{"prunedResult": {"rec_texts": [], "rec_boxes": []}}],
        ):
            with (
                self.subTest(observations=observations),
                patch.object(
                    caches, "_paddlex_ocr_url", return_value="http://127.0.0.1:1/ocr"
                ),
                self._response({"result": {"ocrResults": observations}}),
            ):
                self.assertEqual(
                    caches._paddlex_payload_from_image(Image.new("RGB", (5, 5))),
                    ([], []),
                )

    def test_invalid_box_or_nontext_cannot_drop_an_original_token(self):
        for text, box in (
            (11, [0, 0, 5, 5]),
            ("11", [False, 0, 5, 5]),
            ("11", [0, 0, float("nan"), 5]),
            ("11", [5, 0, 0, 5]),
        ):
            payload = {
                "result": {
                    "ocrResults": [
                        {"prunedResult": {"rec_texts": [text], "rec_boxes": [box]}}
                    ]
                }
            }
            with (
                self.subTest(text=text, box=box),
                patch.object(
                    caches, "_paddlex_ocr_url", return_value="http://127.0.0.1:1/ocr"
                ),
                self._response(payload),
                self.assertRaises(RuntimeError),
            ):
                caches._paddlex_payload_from_image(Image.new("RGB", (5, 5)))

    def test_requested_foreign_or_noninteger_page_never_silently_disappears(self):
        for index in (-1, 3, True, "1", 1.0):
            with self.subTest(index=index), self.assertRaises(ValueError):
                caches.build_page_ocr_cache(str(self.pdf), [index], workers=1)

    def test_resume_keeps_unconsumed_original_source_fields(self):
        target = self.root / "extensions.json"
        note = {
            "origin": "Controlled original source extension; not scientific acceptance"
        }
        write_json_atomic(
            target,
            {
                "metadata": caches.build_cache_metadata(str(self.pdf)),
                "page_texts": {"0": "Original native page zero"},
                "ocr_line_map": {},
                "original_diagnostics": note,
            },
        )
        value = caches.update_page_ocr_cache(str(self.pdf), [0, 1, 2], str(target))
        self.assertEqual(value["original_diagnostics"], note)
        self.assertEqual(json.loads(target.read_text())["original_diagnostics"], note)

    def test_existing_rapidocr_reads_a_controlled_raster_with_original_coordinates(
        self,
    ):
        # Actual installed CPU OCR, not extraction/chemical acceptance evidence.
        # Uses the package's existing models; no download/provider/private input.
        pdf = self.root / "controlled-raster.pdf"
        with fitz.open() as source:
            page = source.new_page(width=500, height=180)
            page.insert_text((40, 85), "CONTROL SOURCE 17", fontsize=28)
            image = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
        with fitz.open() as document:
            page = document.new_page(width=500, height=180)
            page.insert_image(page.rect, stream=image)
            document.save(pdf)
        with (
            patch.dict("os.environ", {"PATENTSAR_PADDLEX_OCR_URL": "off"}),
            patch.object(caches, "_OCR_ENGINE", None),
        ):
            value = caches.update_page_ocr_cache(
                str(pdf), [0], str(self.root / "raster.json")
            )
        self.assertIn("CONTROL", value["page_texts"]["0"])
        self.assertTrue(value["ocr_line_map"]["0"])
        self.assertTrue(
            all(
                line["geometry_space"] == "rendered"
                for line in value["ocr_line_map"]["0"]
            )
        )
