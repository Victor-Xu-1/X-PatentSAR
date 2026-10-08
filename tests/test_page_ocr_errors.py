"""Known observation faults stay explicit; unknown failures cannot become empty OCR."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_web_support import WebFixture

from patent_sar_extractor.core import page_ocr_cache as caches


class UnexpectedBackendError(Exception):
    pass


class PageOCRErrorTests(WebFixture, unittest.TestCase):
    def test_unknown_initialization_fault_cannot_start_a_competing_backend(self):
        def fail(**_kwargs):
            raise UnexpectedBackendError("controlled unknown SDK fault")

        with (
            patch.object(caches, "_paddlex_ocr_url", return_value=""),
            patch.object(caches, "_allow_tesseract_fallback", return_value=True),
            patch.dict(
                sys.modules, {"rapidocr_onnxruntime": SimpleNamespace(RapidOCR=fail)}
            ),
            self.assertRaises(UnexpectedBackendError),
        ):
            caches._build_ocr_engine()

    def test_known_missing_engine_is_not_misrepresented_as_a_working_engine(self):
        def missing(**_kwargs):
            raise OSError("controlled missing runtime")

        with (
            patch.object(caches, "_paddlex_ocr_url", return_value=""),
            patch.object(caches, "_allow_tesseract_fallback", return_value=False),
            patch.dict(
                sys.modules, {"rapidocr_onnxruntime": SimpleNamespace(RapidOCR=missing)}
            ),
        ):
            self.assertIs(caches._build_ocr_engine(), False)


if __name__ == "__main__":
    unittest.main()
