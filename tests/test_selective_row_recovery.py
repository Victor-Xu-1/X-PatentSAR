"""Preserve agreeing original rows; acquire auxiliary text only for real gaps."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.cell_raster import render_cell_raster
from patent_sar_extractor.core.table_cells import observe_original_cell
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_proof import (
    replay_auxiliary_cell,
    valid_auxiliary_cell,
)
from patent_sar_extractor.core.text_ocr.source_inventory import auxiliary_source_cells
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary


class SelectiveRowRecoveryTests(unittest.TestCase):
    def setUp(self):
        document = fitz.open()
        self.addCleanup(document.close)
        self.page = document.new_page(width=200, height=170)
        self.labels = ("HTRF", "Target Q", "EC50", "nM")
        for index, text in enumerate(self.labels):
            self.page.insert_text((25, 40 + 20 * index), text, fontsize=9)
        self.bounds = [15, 22, 160, 118]
        self.images = tuple(
            render_cell_raster(self.page, self.bounds, dpi, purpose="text").image
            for dpi in (400, 600)
        )
        self.primaries = tuple(self.primary(dpi) for dpi in (400, 600))

    def primary(self, dpi, *, changed=None, weak_index=0):
        values = []
        for index, text in enumerate(self.labels):
            text = changed if changed is not None and index == 2 else text
            values.extend([(text, 0.2)] * 2 if index == weak_index else [(text, 0.96)])
        sequence = iter(values)

        def reader(image, *, use_det, use_cls):
            return ([], None) if use_det else ([list(next(sequence))], None)

        return observe_original_cell(
            self.page, self.bounds, "header", dpi, reader, lambda text, _kind: text
        ).evidence(dpi, self.bounds)

    def recover(self):
        reader = ControlledAuxiliary(("HTRF",))
        before = copy.deepcopy(self.primaries)
        result = refine_text_pair(self.images, self.primaries, reader)
        self.assertEqual(self.primaries, before)
        self.assertIsNotNone(result)
        return result, reader

    def test_only_unresolved_rows_call_model_and_primary_scores_are_not_invented(self):
        result, reader = self.recover()
        self.assertEqual(reader.calls, 2)
        packet = result[0]["auxiliary_text"]
        for view, primary in zip(packet["views"], self.primaries, strict=True):
            requests = view["requests"]
            self.assertEqual(len(requests), 4)
            self.assertIn("observations", requests[0])
            for index in range(1, 4):
                self.assertEqual(requests[index]["retained_primary_row"], index)
                self.assertNotIn("observations", requests[index])
                self.assertEqual(
                    view["selected"]["parts"][index], primary["parts"][index]
                )
        self.assertEqual(result[0]["raw_text"].splitlines(), list(self.labels))
        self.assertEqual(len(list(auxiliary_source_cells([(1, result[0])]))), 1)

    def test_serialized_replay_is_model_free_and_retains_all_original_ink(self):
        result, _reader = self.recover()
        with patch(
            "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
            side_effect=AssertionError("Readback must never load a model"),
        ):
            for reading, dpi in zip(result, (400, 600), strict=True):
                self.assertTrue(valid_auxiliary_cell(reading, dpi))
                self.assertTrue(replay_auxiliary_cell(reading, self.page))
            self.page.insert_text((28, 108), "extra", fontsize=6)
            self.assertFalse(replay_auxiliary_cell(result[0], self.page))

    def test_missing_changed_or_promoted_primary_rows_are_not_new_evidence(self):
        result, _reader = self.recover()
        for mutation in (
            "index",
            "pixel",
            "text",
            "score",
            "missing",
            "weak",
            "invented_request",
        ):
            with self.subTest(mutation=mutation):
                reading = copy.deepcopy(result[0])
                view = reading["auxiliary_text"]["views"][0]
                row = view["requests"][1]
                if mutation == "index":
                    row["retained_primary_row"] = 2
                elif mutation == "pixel":
                    row["source_pixel_sha256"] = "f" * 64
                elif mutation in ("text", "score"):
                    key, value = (
                        ("text", "Target R")
                        if mutation == "text"
                        else ("confidence", 0.999)
                    )
                    view["selected"]["parts"][1][key] = value
                elif mutation == "missing":
                    view["requests"].pop(1)
                elif mutation == "weak":
                    view["requests"][0] = copy.deepcopy(row)
                    view["requests"][0]["retained_primary_row"] = 0
                else:
                    row["observations"] = copy.deepcopy(
                        view["requests"][0]["observations"]
                    )
                self.assertFalse(
                    valid_auxiliary_cell(reading, 400)
                    and replay_auxiliary_cell(reading, self.page)
                )

    def test_known_unit_or_endpoint_disagreement_never_calls_auxiliary(self):
        for changed in ("IC50", "AC50"):
            primaries = (self.primaries[0], self.primary(600, changed=changed))
            reader = ControlledAuxiliary()
            evidence = []
            self.assertIsNone(
                refine_text_pair(self.images, primaries, reader, evidence_sink=evidence)
            )
            self.assertEqual(reader.calls, 0)
            self.assertEqual(evidence[0]["code"], "conflicting_retained_primary_claims")

    def test_different_unresolved_row_positions_do_not_reuse_a_weak_peer(self):
        primaries = (self.primaries[0], self.primary(600, weak_index=1))
        reader = ControlledAuxiliary(("HTRF", "Target Q"))
        result = refine_text_pair(self.images, primaries, reader)
        self.assertIsNotNone(result)
        self.assertEqual(reader.calls, 4)
        self.assertTrue(replay_auxiliary_cell(result[0], self.page))
