"""Auxiliary cells retain primaries and must replay against complete original rows."""

import copy
import unittest

import fitz

from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.cell_text_proof import (
    physical_text_valid,
    valid_text_components,
)
from patent_sar_extractor.core.table_cells import cell_image
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_proof import (
    replay_auxiliary_cell,
    valid_auxiliary_cell,
)
from patent_sar_extractor.core.text_ocr.protocol import frame_digest


class ControlledAuxiliary:
    def __init__(self, texts=("HTRF", "EC50")):
        self.texts = texts
        self.calls = 0

    def observe(self, image):
        text = self.texts[self.calls % len(self.texts)]
        self.calls += 1
        return {
            "id": f"{self.calls:032x}",
            "status": "observed",
            "image_sha256": "a" * 64,
            "pixel_sha256": frame_digest(image),
            "model_fingerprint": "b" * 64,
            "text": text,
            "confidence": 0.999,
            "confidence_kind": "uncalibrated_model",
            "device": "cpu",
            "peak_rss_mb": 512.0,
            "cache_hit": False,
        }


def primary(image, *, use_det, use_cls):
    if use_det:
        return [], None
    return [["weak", 0.2]], None


class AuxiliaryCellEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=200, height=160)
        self.page.insert_text((25, 45), "HTRF", fontsize=9)
        self.page.insert_text((25, 65), "EC50", fontsize=9)
        self.bounds = [15, 25, 140, 80]
        self.images = tuple(cell_image(self.page, self.bounds, d) for d in (400, 600))
        self.primaries = tuple(
            observe_cell(i, "header", d, primary, lambda t, _k: t).evidence(
                d, self.bounds
            )
            for i, d in zip(self.images, (400, 600))
        )

    def test_whole_original_pair_and_weak_primaries_are_preserved(self):
        before = copy.deepcopy(self.primaries)
        reader = ControlledAuxiliary()
        pair = refine_text_pair(self.images, self.primaries, reader)
        self.assertIsNotNone(pair)
        self.assertEqual(reader.calls, 4)
        self.assertEqual(self.primaries, before)
        for reading, dpi in zip(pair, (400, 600)):
            self.assertEqual(reading["raw_text"], "HTRF\nEC50")
            self.assertTrue(valid_auxiliary_cell(reading, dpi))
            self.assertTrue(replay_auxiliary_cell(reading, self.page))
            self.assertEqual(
                reading["auxiliary_text"]["views"][0]["primary"], before[0]
            )

    def test_saved_flags_cannot_hide_tampered_source_or_removed_observations(self):
        pair = refine_text_pair(self.images, self.primaries, ControlledAuxiliary())
        for change in ("text", "primary", "model", "row", "pixels", "score"):
            reading = copy.deepcopy(pair[0])
            packet = reading["auxiliary_text"]
            if change == "text":
                reading["raw_text"] = reading["text"] = "IC50"
            elif change == "primary":
                packet["views"][0]["primary"] = {}
            elif change == "model":
                packet["views"][0]["requests"][0]["observations"][0][
                    "model_fingerprint"
                ] = "c" * 64
            elif change == "row":
                packet["views"][0]["requests"].pop()
            elif change == "pixels":
                packet["views"][0]["frame"]["pixel_sha256"] = "c" * 64
            else:
                packet["views"][0]["requests"][0]["observations"][0]["confidence"] = 0.9
            self.assertFalse(
                valid_auxiliary_cell(reading, 400)
                and replay_auxiliary_cell(reading, self.page),
                change,
            )

    def test_disagreeing_complete_reads_are_not_voted_or_spliced(self):
        reader = ControlledAuxiliary(("HTRF", "EC50", "HTRF", "IC50"))
        self.assertIsNone(refine_text_pair(self.images, self.primaries, reader))

    def test_original_native_and_physical_column_metadata_cannot_be_rewritten(self):
        from patent_sar_extractor.core.text_ocr.cell_proof import effective_cells

        primaries = copy.deepcopy(self.primaries)
        for primary in primaries:
            primary.update(
                native_text="Original source", physical_column=2, crosses_boundary=False
            )
        recovered = refine_text_pair(self.images, primaries, ControlledAuxiliary())
        self.assertIsNotNone(recovered)
        for field, changed in (
            ("native_text", ""),
            ("physical_column", 3),
            ("crosses_boundary", True),
        ):
            with self.subTest(field=field):
                packet = copy.deepcopy(recovered[0]["auxiliary_text"])
                packet["views"][0]["selected"][field] = changed
                with self.assertRaises(ValueError):
                    effective_cells(packet)

    def test_extra_source_ink_cannot_reuse_an_old_proof(self):
        pair = refine_text_pair(self.images, self.primaries, ControlledAuxiliary())
        self.page.insert_text((30, 76), "nM", fontsize=6)
        self.assertFalse(replay_auxiliary_cell(pair[0], self.page))

    def test_valid_primary_never_starts_auxiliary_inference(self):
        def good(image, *, use_det, use_cls):
            return ([], None) if use_det else ([["HTRF", 0.99]], None)

        images = self.images
        readings = tuple(
            observe_cell(i, "header", d, good, lambda t, _k: t).evidence(d, self.bounds)
            for i, d in zip(images, (400, 600))
        )
        reader = ControlledAuxiliary()
        self.assertIsNone(refine_text_pair(images, readings, reader))
        self.assertEqual(reader.calls, 0)

    def test_auxiliary_cannot_bypass_stricter_row_scope_or_drop_its_packet(self):
        pair = refine_text_pair(self.images, self.primaries, ControlledAuxiliary())
        self.assertTrue(valid_text_components(pair[0], 400))
        self.assertFalse(valid_text_components(pair[0], 400, maximum_rows=1))
        self.assertFalse(valid_text_components(pair[0], 400, maximum_row_height=True))
        stripped = copy.deepcopy(pair[0])
        del stripped["auxiliary_text"]
        self.assertFalse(valid_text_components(stripped, 400))

    def test_malformed_serialized_packets_fail_closed_without_type_crashes(self):
        for value in (
            None,
            [],
            "observed",
            {"physical_header_lines": []},
            {"physical_header_lines": "observed"},
        ):
            with self.subTest(value=value):
                self.assertFalse(valid_text_components(value, 400))
                self.assertFalse(
                    physical_text_valid(
                        value,
                        packet_name="physical_header_lines",
                        part_method="physical_header_line",
                        minimum_rows=2,
                        maximum_rows=8,
                    )
                )
