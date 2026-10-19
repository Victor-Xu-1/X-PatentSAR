"""Original pixels and qualified text are independent, including rejected cells."""

import copy
import hashlib
import json
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.cell_frame_proof import original_cell_frame_matches
from patent_sar_extractor.core.cell_text_chunks import observe_text_cell
from patent_sar_extractor.core.cell_text_proof import valid_text_reading
from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.table_cells import cell_image


class UnresolvedChunkSourceTests(unittest.TestCase):
    def original(self, *, tall=False, score=0.2, maximum=32):
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=240, height=520)
        if tall:
            page.draw_rect(fitz.Rect(30, 35, 140, 120), color=(0, 0, 0))
        else:
            for row in range(40):
                page.insert_text((25, 35 + 11 * row), "1H NMR", fontsize=6)
        bounds = [10, 20, 190, 480]

        def reader(image, *, use_det, use_cls):
            if tall:
                self.fail("A refused physical row cannot trigger another OCR attempt")
            return ([], None) if use_det else ([["1H NMR", score]], None)

        readings = []
        for dpi in (400, 600):
            image = cell_image(page, bounds, dpi)
            reading = observe_text_cell(
                image, dpi, reader, rows_per_chunk=maximum
            ).evidence(dpi, bounds)
            reading["source_frame"] = {
                "dpi": dpi,
                "shape": list(image.shape),
                "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
            }
            readings.append(json.loads(json.dumps(reading)))
        return page, readings

    def assert_unqualified_original(self, page, readings, *, maximum=32):
        with (
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Source replay cannot recognize text"),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                side_effect=AssertionError("Source replay cannot load a model"),
            ),
        ):
            for reading in readings:
                self.assertFalse(
                    valid_text_reading(
                        reading,
                        reading["bbox"],
                        reading["render_dpi"],
                        maximum_rows=maximum,
                        allow_chunks=True,
                    )
                )
                self.assertTrue(original_cell_frame_matches(reading, page))
            self.assertEqual(
                original_role_source_errors(page.parent, [(1, c) for c in readings]),
                [],
            )

    def test_unsegmentable_ink_retains_source_but_never_becomes_text(self):
        page, readings = self.original(tall=True)
        self.assertEqual(readings[0]["physical_text_chunks"]["row_bounds"], [])
        self.assert_unqualified_original(page, readings)

    def test_weak_complete_slices_retain_source_without_qualifying_text(self):
        for maximum in (8, 32):
            with self.subTest(maximum=maximum):
                page, readings = self.original(maximum=maximum)
                self.assertEqual(
                    readings[0]["physical_text_chunks"]["status"], "unresolved"
                )
                self.assert_unqualified_original(page, readings, maximum=maximum)

    def test_observed_text_and_changed_original_remain_strict(self):
        page, readings = self.original(score=0.99)
        for reading in readings:
            self.assertTrue(original_cell_frame_matches(reading, page))
            self.assertTrue(
                valid_text_reading(
                    reading,
                    reading["bbox"],
                    reading["render_dpi"],
                    maximum_rows=32,
                    allow_chunks=True,
                )
            )
        page.insert_text((30, 476), "extra", fontsize=6)
        for reading in readings:
            self.assertFalse(original_cell_frame_matches(reading, page))

    def test_rejected_source_cannot_hide_missing_reordered_or_forged_slices(self):
        page, readings = self.original()
        for mutation in (
            "missing",
            "reordered",
            "hash",
            "rows",
            "ink",
            "status",
            "raw",
            "child_crop",
            "child_frame",
        ):
            with self.subTest(mutation=mutation):
                reading = copy.deepcopy(readings[0])
                packet = reading["physical_text_chunks"]
                if mutation == "missing":
                    packet["chunks"].pop()
                elif mutation == "reordered":
                    packet["chunks"].reverse()
                elif mutation == "hash":
                    packet["chunks"][0]["pixel_sha256"] = "f" * 64
                elif mutation == "rows":
                    packet["row_bounds"].clear()
                    packet["chunks"].clear()
                elif mutation == "ink":
                    packet["ink_pixels"] -= 1
                elif mutation == "status":
                    packet["status"] = "observed"
                elif mutation == "raw":
                    reading["raw_text"] += " invented"
                elif mutation == "child_frame":
                    del packet["chunks"][0]["reading"]["physical_header_lines"]
                else:
                    packet["chunks"][0]["reading"]["ink_crop_pixels"][0] += 1
                self.assertFalse(original_cell_frame_matches(reading, page))

    def test_actual_binding_and_activity_consumers_preserve_rejected_role(self):
        from patent_sar_extractor.core.activity_auxiliary_replay import (
            original_activity_source_errors,
        )
        from patent_sar_extractor.core.binding_original_replay import (
            original_binding_source_errors,
        )
        from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
        from patent_sar_extractor.core.source_role_observations import (
            role_failure,
            scope_observations,
            serialize_role_observations,
        )
        from tests.test_web_acceptance import complete_payloads

        for tall in (True, False):
            with self.subTest(tall=tall):
                page, readings = self.original(tall=tall)
                x0, y0, x1, y1 = readings[0]["bbox"]
                cells = {
                    "xs": [x0, x1],
                    "ys": [y0, y1],
                    "native_hints": [[""]],
                    "observations": [
                        {"method": c["method"], "matrix": [[c["text"]]], "cells": [c]}
                        for c in readings
                    ],
                }
                failed = role_failure(
                    "unqualified_role_observations",
                    cells,
                    "Unknown original table",
                    cells,
                )
                payload = complete_payloads()["bindings"]
                baseline = recognition_inputs(copy.deepcopy(payload))
                payload["source_role_observations"] = serialize_role_observations(
                    scope_observations(
                        [failed],
                        1,
                        original_pdf_sha256=payload["source_reference_scope"][
                            "original_pdf_sha256"
                        ],
                    )
                )
                plan = recognition_inputs(payload)
                self.assertEqual(plan.work_items, baseline.work_items)
                self.assertEqual(len(plan.role_text), 2)
                self.assertEqual(
                    original_binding_source_errors(
                        page.parent, [], role_text=plan.role_text
                    ),
                    [],
                )
                activity = {
                    "rows": [],
                    "header_observations": {},
                    "source_role_observations": payload["source_role_observations"],
                }
                self.assertEqual(
                    original_activity_source_errors(
                        activity,
                        open_original=lambda page=page: nullcontext(page.parent),
                    ),
                    [],
                )
                self.assertEqual(
                    next(iter(payload["source_role_observations"].values()))["status"],
                    "unresolved",
                )
                self.assertEqual(
                    payload.get("acceptance"),
                    complete_payloads()["bindings"].get("acceptance"),
                )
                page.insert_text((30, 476), "changed", fontsize=6)
                self.assertTrue(
                    original_binding_source_errors(
                        page.parent, [], role_text=plan.role_text
                    )
                )
                self.assertTrue(
                    original_activity_source_errors(
                        activity,
                        open_original=lambda page=page: nullcontext(page.parent),
                    )
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
