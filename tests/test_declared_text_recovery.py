"""Declared text uses the same optional paired recovery and original readback."""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.core.activity_text_capture import capture_text_page
from patent_sar_extractor.core.activity_text_sources import text_page_qualified
from patent_sar_extractor.core.source_geometry import native_lines, source_layout
from patent_sar_extractor.core.source_page_lines import observed_page_text
from patent_sar_extractor.core.text_ocr.process import TextOCRCancelled
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary, primary
from tests.test_declared_text_original import TEXT

RUNTIME_GETTER = (
    "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime"
)


class DeclaredTextRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        with fitz.open() as native:
            page = native.new_page(width=480, height=240)
            page.insert_text((40, 60), TEXT, fontsize=9)
            # Simulate the independent raster locator's original line boxes,
            # not the native-source window partition being verified.
            self.proposals = [
                {"text": line["text"], "bbox": line["bbox"]}
                for line in native_lines(source_layout(page))
            ]
            image = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            self.document.new_page(width=480, height=240).insert_image(
                page.rect, stream=image.tobytes("png")
            )
        self.reader = ControlledAuxiliary(
            tuple(text for text in TEXT.splitlines() for _ in (400, 600))
        )

    def capture(self, *, reader=True):
        proposals = copy.deepcopy(self.proposals)
        before = copy.deepcopy(proposals)
        with (
            patch(
                "patent_sar_extractor.core.activity_text_capture.get_ocr_engine",
                return_value=("rapidocr", primary),
            ),
            patch(
                RUNTIME_GETTER, return_value=self.reader if reader else None
            ) as getter,
        ):
            source = capture_text_page(self.document[0], TEXT, proposals)
        self.assertEqual(proposals, before)
        return source, getter

    def payload(self, source):
        return {
            "coverage": {
                "text_pages": {"1": observed_page_text(source)},
                "text_sources": {"1": source},
            },
            "rows": [],
        }

    def test_weak_declared_source_can_use_existing_optional_paired_reader(self):
        source, getter = self.capture()
        self.assertTrue(text_page_qualified(source, observed_page_text(source)))
        self.assertEqual(getter.call_count, len(self.proposals))
        self.assertEqual(self.reader.calls, 2 * len(self.proposals))
        for line in source["lines"]:
            self.assertTrue(
                all("auxiliary_text" in reading for reading in line["observations"])
            )

    def test_sole_parser_receives_qualified_readings_and_keeps_original_number(self):
        source, _getter = self.capture()
        parsed = extract_text_tables(
            [0], {"0": TEXT}, source_reader=lambda _index, _text: source
        )
        self.assertEqual([row.cpd for row in parsed.rows], ["Compound 31"])
        self.assertEqual(parsed.rows[0].activity_values, {"IC50 (nM)": "9"})
        self.assertFalse(parsed.rows[0].needs_review)

    def test_recovered_source_replays_without_models_and_rejects_changed_pixels(self):
        source, _getter = self.capture()
        payload = self.payload(source)
        with patch(
            RUNTIME_GETTER, side_effect=AssertionError("Readback cannot start OCR")
        ):
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(self.document)
                ),
                [],
            )
            self.document[0].draw_rect(
                self.document[0].rect, color=None, fill=(1, 1, 1)
            )
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(self.document)
                )
            )

    def test_off_or_unavailable_runtime_does_not_promote_primary_weak_text(self):
        source, _getter = self.capture(reader=False)
        self.assertFalse(text_page_qualified(source, observed_page_text(source)))
        self.assertEqual(self.reader.calls, 0)
        parsed = extract_text_tables(
            [0], {"0": TEXT}, source_reader=lambda _index, _text: source
        )
        self.assertEqual([row.cpd for row in parsed.rows], ["Compound 31"])
        self.assertTrue(all(row.needs_review for row in parsed.rows))

    def test_native_text_never_requests_auxiliary_runtime(self):
        with fitz.open() as native:
            page = native.new_page()
            page.insert_text((40, 60), TEXT, fontsize=9)
            with patch(
                RUNTIME_GETTER,
                side_effect=AssertionError("Native text cannot start auxiliary OCR"),
            ):
                source = capture_text_page(page, page.get_text("text"))
            self.assertTrue(text_page_qualified(source, observed_page_text(source)))

    def test_timeout_preserves_weak_primaries_and_rejected_attempts(self):
        with patch.object(
            self.reader, "observe", side_effect=TimeoutError("controlled timeout")
        ):
            source, _getter = self.capture()
        self.assertFalse(text_page_qualified(source, observed_page_text(source)))
        self.assertTrue(
            any(
                "auxiliary_text_attempts" in reading
                for line in source["lines"]
                for reading in line["observations"]
            )
        )

    def test_cancellation_propagates_instead_of_becoming_partial_success(self):
        with (
            patch.object(
                self.reader,
                "observe",
                side_effect=TextOCRCancelled("controlled cancellation"),
            ),
            self.assertRaises(TextOCRCancelled),
        ):
            self.capture()

    def test_independent_native_conflict_cannot_be_rewritten_by_auxiliary_text(self):
        self.document[0].insert_text((45, 60), "X", fontsize=9)
        source, _getter = self.capture()
        self.assertFalse(text_page_qualified(source, observed_page_text(source)))
        self.assertTrue(
            any(
                reading.get("native_role") == "witness" and reading.get("text") == "X"
                for line in source["lines"]
                for reading in line["observations"]
            )
        )

    def test_complete_known_primary_disagreement_never_invokes_auxiliary(self):
        class DisagreeingPrimary:
            calls = 0

            def __call__(self, image, *, use_det, use_cls):
                if use_det:
                    return [], None
                text = ("known A", "known B")[self.calls % 2]
                self.calls += 1
                return [[text, 0.999]], None

        engine = DisagreeingPrimary()
        with (
            patch(
                "patent_sar_extractor.core.activity_text_capture.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
            patch(
                RUNTIME_GETTER,
                side_effect=AssertionError(
                    "Known source contradictions cannot trigger a vote"
                ),
            ),
        ):
            source = capture_text_page(self.document[0], TEXT, self.proposals)
        self.assertNotEqual(
            source["lines"][0]["observations"][0]["text"],
            source["lines"][0]["observations"][1]["text"],
        )
        self.assertFalse(text_page_qualified(source, observed_page_text(source)))

    def test_agreeing_auxiliary_text_below_existing_quality_gate_stays_unresolved(self):
        class LowScore(ControlledAuxiliary):
            def observe(self, image):
                return {**super().observe(image), "confidence": 0.95}

        self.reader = LowScore(
            tuple(text for text in TEXT.splitlines() for _ in (400, 600))
        )
        source, _getter = self.capture()
        self.assertFalse(text_page_qualified(source, observed_page_text(source)))
        self.assertTrue(
            all(
                "auxiliary_text" not in reading
                for line in source["lines"]
                for reading in line["observations"]
            )
        )
