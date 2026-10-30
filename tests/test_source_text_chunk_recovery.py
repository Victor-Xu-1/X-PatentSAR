"""Complete long primary observations must not load a recovery model to vote."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.cell_raster import render_cell_raster
from patent_sar_extractor.core.cell_text_chunks import observe_text_cell
from patent_sar_extractor.core.cell_text_proof import valid_text_reading
from patent_sar_extractor.core.text_ocr.cell_proof import (
    replay_auxiliary_cell,
    valid_auxiliary_cell,
)
from patent_sar_extractor.core.text_ocr.process import TextOCRCancelled
from patent_sar_extractor.core.text_ocr.source_capture import refine_source_text
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary


def original_text_reading(page, bounds, dpi, engine, *, rows):
    """Use current physical source windows, not an unowned image-only fixture."""
    raster = render_cell_raster(page, bounds, dpi, purpose="text")
    reading = observe_text_cell(raster.image, dpi, engine, rows_per_chunk=rows)
    return {
        **reading.evidence(dpi, bounds),
        "source_frame": raster.frame,
        "source_window": raster.source_window,
    }


class SourceTextChunkRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=240, height=520)
        for row in range(40):
            self.page.insert_text((25, 35 + 11 * row), "1H NMR", fontsize=6)
        self.bounds = [10, 20, 190, 480]

        def reader(image, *, use_det, use_cls):
            return ([], None) if use_det else ([["1H NMR", 0.99]], None)

        self.readings = [
            original_text_reading(self.page, self.bounds, dpi, reader, rows=32)
            for dpi in (400, 600)
        ]
        for reading, dpi in zip(self.readings, (400, 600)):
            self.assertTrue(
                valid_text_reading(
                    reading, self.bounds, dpi, maximum_rows=32, allow_chunks=True
                )
            )

    def test_complete_primary_chunks_never_load_an_auxiliary_model(self):
        before = copy.deepcopy(self.readings)
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError(
                "Clear whole original chunks cannot trigger voting"
            ),
        ):
            self.assertEqual(
                refine_source_text(self.page, self.bounds, self.readings), before
            )

    def test_incomplete_tail_remains_unqualified_without_source_or_text_repair(self):
        readings = copy.deepcopy(self.readings)
        readings[0]["physical_text_chunks"]["chunks"].pop()
        before = copy.deepcopy(readings)
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            return_value=None,
        ) as runtime:
            result = refine_source_text(self.page, self.bounds, readings)
        runtime.assert_not_called()
        for old, selected in zip(before, result, strict=True):
            self.assertEqual(
                {
                    key: value
                    for key, value in selected.items()
                    if key != "auxiliary_text_attempts"
                },
                old,
            )
            self.assertEqual(
                selected["auxiliary_text_attempts"],
                [
                    {
                        "status": "not_attempted",
                        "code": "conflicting_retained_primary_claims",
                    }
                ],
            )
        self.assertFalse(
            valid_text_reading(
                result[0], self.bounds, 400, maximum_rows=32, allow_chunks=True
            )
        )

    def recover(self, *, reader=None, maximum_rows=32, allow_chunks=True):
        def weak(image, *, use_det, use_cls):
            return ([], None) if use_det else ([["1H NMR", 0.2]], None)

        readings = [
            original_text_reading(self.page, self.bounds, dpi, weak, rows=32)
            for dpi in (400, 600)
        ]
        reader = ControlledAuxiliary(("1H NMR",)) if reader is None else reader
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            return_value=reader,
        ):
            result = refine_source_text(
                self.page,
                self.bounds,
                readings,
                maximum_rows=maximum_rows,
                allow_chunks=allow_chunks,
            )
        return readings, result, reader

    def test_weak_long_cell_recovers_every_original_row_without_truncation(self):
        _primary, result, reader = self.recover()
        self.assertEqual(
            reader.calls,
            80,
            "All40physical rows in BOTH original views need their own bounded observation",
        )
        for reading, dpi in zip(result, (400, 600)):
            self.assertEqual(len(reading["raw_text"].splitlines()), 40)
            self.assertTrue(
                valid_text_reading(
                    reading, self.bounds, dpi, maximum_rows=32, allow_chunks=True
                )
            )

    def test_recovered_chunks_replay_actual_pixels_without_any_models(self):
        _primary, result, _reader = self.recover()
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError("Read-side model loading is forbidden"),
        ):
            for reading, dpi in zip(result, (400, 600)):
                self.assertTrue(valid_auxiliary_cell(reading, dpi))
                self.assertTrue(replay_auxiliary_cell(reading, self.page))
            self.page.insert_text((30, 476), "extra", fontsize=6)
            self.assertFalse(replay_auxiliary_cell(result[0], self.page))

    def test_missing_extra_or_changed_requests_and_removed_marker_cannot_replay(self):
        _primary, baseline, _reader = self.recover()
        for mutation in (
            "missing",
            "extra",
            "pixels",
            "model",
            "selected",
            "marker",
            "packet",
            "both_markers",
            "huge_score",
        ):
            with self.subTest(mutation=mutation):
                reading = copy.deepcopy(baseline[0])
                packet = reading["auxiliary_text"]
                requests = packet["views"][0]["requests"]
                if mutation == "missing":
                    requests.pop()
                elif mutation == "extra":
                    requests.append(copy.deepcopy(requests[0]))
                elif mutation == "pixels":
                    requests[0]["observations"][0]["pixel_sha256"] = "f" * 64
                elif mutation == "model":
                    requests[0]["observations"][0]["model_fingerprint"] = "f" * 64
                elif mutation == "selected":
                    packet["views"][0]["selected"]["raw_text"] += " changed"
                elif mutation == "marker":
                    del reading["auxiliary_text_version"]
                elif mutation == "packet":
                    del reading["auxiliary_text"]
                elif mutation == "both_markers":
                    del reading["auxiliary_text"]
                    del reading["auxiliary_text_version"]
                else:
                    requests[0]["observations"][0]["confidence"] = 10**400
                self.assertFalse(
                    valid_auxiliary_cell(reading, 400)
                    and replay_auxiliary_cell(reading, self.page)
                )
                if mutation in {"marker", "packet", "both_markers"}:
                    self.assertFalse(
                        valid_text_reading(
                            reading,
                            self.bounds,
                            400,
                            maximum_rows=32,
                            allow_chunks=True,
                        )
                    )

    def test_disagreeing_complete_views_are_not_voted(self):
        _primary, result, reader = self.recover(
            reader=ControlledAuxiliary(tuple(["1H NMR"] * 40 + ["changed"] * 40))
        )
        self.assertEqual(reader.calls, 80)
        self.assertNotIn("auxiliary_text", result[0])
        self.assertFalse(
            valid_text_reading(
                result[0], self.bounds, 400, maximum_rows=32, allow_chunks=True
            )
        )

    def test_scalar_scope_does_not_silently_acquire_long_role_permissions(self):
        _primary, result, reader = self.recover(maximum_rows=8, allow_chunks=False)
        self.assertEqual(reader.calls, 0)
        self.assertNotIn("auxiliary_text", result[0])

    def test_differing_rows_conserve_every_eight_and_thirty_two_row_boundary(self):
        for count, maximum in ((8, 8), (9, 8), (32, 32), (33, 32)):
            with self.subTest(count=count, maximum=maximum), fitz.open() as document:
                page = document.new_page(width=240, height=480)
                labels = tuple(
                    f"1H NMR (400 MHz) {7 + i / 100:.2f} ppm" for i in range(count)
                )
                for i, text in enumerate(labels):
                    page.insert_text((25, 35 + 11 * i), text, fontsize=6)
                bounds = [10, 20, 190, 460]

                def weak(image, *, use_det, use_cls):
                    return ([], None) if use_det else ([["weak", 0.2]], None)

                readings = [
                    original_text_reading(page, bounds, dpi, weak, rows=maximum)
                    for dpi in (400, 600)
                ]
                reader = ControlledAuxiliary(labels)
                with patch(
                    "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                    return_value=reader,
                ):
                    recovered = refine_source_text(
                        page, bounds, readings, maximum_rows=maximum, allow_chunks=True
                    )
                self.assertEqual(reader.calls, 2 * count)
                for cell, dpi in zip(recovered, (400, 600)):
                    self.assertEqual(cell["text"].splitlines(), list(labels))
                    self.assertTrue(
                        valid_text_reading(
                            cell, bounds, dpi, maximum_rows=maximum, allow_chunks=True
                        )
                    )
                    self.assertTrue(replay_auxiliary_cell(cell, page))

    def test_request_budget_and_cancellation_cannot_return_partial_success(self):
        with patch("patent_sar_extractor.core.text_ocr.source_inventory._MAX_ROWS", 10):
            _primary, result, reader = self.recover()
        self.assertEqual(reader.calls, 10)
        self.assertNotIn("auxiliary_text", result[0])

        class Cancelled(ControlledAuxiliary):
            def observe(self, image):
                raise TextOCRCancelled("controlled cancellation")

        with self.assertRaises(TextOCRCancelled):
            self.recover(reader=Cancelled())
