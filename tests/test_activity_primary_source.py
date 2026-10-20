"""All ordinary activity cells must retain their actual original pixel owner."""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.table_cells import observe_original_cell


class PrimaryActivitySourceTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=240, height=160)
        self.page.insert_text((30, 45), "Binding", fontsize=9)
        self.page.insert_text((30, 65), "EC50 (pM)", fontsize=9)
        self.bounds = [20, 25, 180, 80]

    def reading(self, *, weak=False):
        def literal(image, *, use_det, use_cls):
            return (
                ([], None)
                if use_det
                else ([["unread" if weak else "row", 0.2 if weak else 0.99]], None)
            )

        return observe_original_cell(
            self.page, self.bounds, "header", 400, literal, lambda text, _kind: text
        ).evidence(400, self.bounds)

    def payload(self, place, reading):
        if place == "header":
            return {
                "header_observations": {
                    "h": {"page_no": 1, "observations": [{"columns": [reading]}]}
                }
            }
        source = {"page_no": 1, "cells": [{"observations": [reading]}]}
        if place == "row":
            return {"rows": [{"activity_sources": [source]}]}
        return {"unresolved_rows": [source]}

    def check(self, payload):
        return original_activity_source_errors(
            payload, open_original=lambda: nullcontext(self.document)
        )

    def test_final_headers_values_and_unresolved_cells_replay_original_pixels(self):
        for index, place in enumerate(("header", "row", "unresolved")):
            with self.subTest(place=place):
                payload = self.payload(place, self.reading())
                self.assertEqual(self.check(payload), [])
                self.page.insert_text((40 + 20 * index, 74), f"{index}nM", fontsize=5)
                self.assertTrue(
                    self.check(payload), "Changed original cell must refuse"
                )

    def test_missing_original_or_frame_and_false_page_owner_refuse(self):
        for place in ("header", "row", "unresolved"):
            reading = self.reading()
            self.assertTrue(
                original_activity_source_errors(self.payload(place, reading))
            )
            missing = copy.deepcopy(reading)
            del missing["source_frame"]
            self.assertTrue(self.check(self.payload(place, missing)))
        payload = self.payload("header", self.reading())
        payload["header_observations"]["h"]["page_no"] = True
        with self.assertRaisesRegex(ValueError, "page ownership"):
            self.check(payload)

    def test_unqualified_text_can_retain_pixels_without_becoming_qualified(self):
        reading = self.reading(weak=True)
        self.assertEqual(reading["text"], "")
        self.assertEqual(self.check(self.payload("header", reading)), [])
        self.assertEqual(reading["text"], "")

    def test_repeated_cell_is_replayed_once_without_loading_any_recognizer(self):
        from patent_sar_extractor.core.cell_frame_proof import (
            original_cell_frame_matches,
        )

        reading = self.reading()
        payload = self.payload("header", reading)
        payload.update(self.payload("row", copy.deepcopy(reading)))
        with (
            patch(
                "patent_sar_extractor.core.activity_auxiliary_replay.original_cell_frame_matches",
                wraps=original_cell_frame_matches,
            ) as replay,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Readback cannot recognize text"),
            ),
        ):
            self.assertEqual(self.check(payload), [])
            self.assertEqual(replay.call_count, 1)

    def test_legacy_native_cell_cannot_supply_current_original_admission(self):
        payload = self.payload("row", {"method": "native_cell", "text": "0.4"})
        # A native cell needs native source identity, never an invented optical
        # frame. Bare legacy dictionaries stay history, not current acceptance.
        self.assertTrue(original_activity_source_errors(payload))
        with patch(
            "patent_sar_extractor.core.activity_auxiliary_replay.original_cell_frame_matches",
            side_effect=AssertionError("Native observations are not optical crops"),
        ):
            self.assertTrue(self.check(payload))

    def test_source_open_failure_is_not_a_model_failure_or_exception_disclosure(self):
        def unavailable():
            raise OSError("controlled private filesystem detail")

        self.assertEqual(
            original_activity_source_errors(
                self.payload("header", self.reading()), open_original=unavailable
            ),
            ["Original activity text replay is unavailable."],
        )

    def test_relabelled_optical_cell_and_incomplete_frame_cannot_hide_ownership(self):
        reading = self.reading()
        reading["method"] = "native_cell"
        for field in ("source_frame", "render_dpi"):
            del reading[field]
        self.assertTrue(self.check(self.payload("row", reading)))

    def test_inventory_limit_applies_before_opening_the_original(self):
        reading = self.reading()
        other = copy.deepcopy(reading)
        other["bbox"][0] += 1
        payload = self.payload("header", reading)
        payload.update(self.payload("row", other))
        with (
            patch(
                "patent_sar_extractor.core.activity_auxiliary_replay.MAX_PRIMARY_SOURCE_CELLS",
                1,
            ),
            self.assertRaisesRegex(ValueError, "bounded inventory"),
        ):
            original_activity_source_errors(payload)

    def test_complete_multi_metric_inventory_does_not_borrow_auxiliary_budget(self):
        from patent_sar_extractor.core.activity_auxiliary_replay import (
            original_primary_cells,
        )

        rows = []
        for index in range(1191):
            cells = []
            for column in range(12):
                cells.append(
                    {
                        "observations": [
                            {
                                "method": f"cell_ocr_{dpi}dpi",
                                "render_dpi": dpi,
                                "bbox": [
                                    20 + column * 35,
                                    20 + index % 40 * 14,
                                    52 + column * 35,
                                    30 + index % 40 * 14,
                                ],
                            }
                            for dpi in (400, 600)
                        ]
                    }
                )
            rows.append(
                {"activity_sources": [{"page_no": 1 + index // 40, "cells": cells}]}
            )
        payload = {"rows": rows}
        self.assertEqual(sum(1 for _ in original_primary_cells(payload)), 1191 * 12 * 2)
        # Capacity is not admission: these locators lack actual captured frames.
        self.assertTrue(original_activity_source_errors(payload))
