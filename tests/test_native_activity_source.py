"""Native measurements require visible original text, never an optical model."""

import copy
import io
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import fitz
from PIL import Image

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout


class NativeActivitySourceTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=240, height=160)
        self.bounds = [20, 25, 100, 55]
        self.page.insert_text((30, 45), "0.4", fontsize=10)

    def reading(self):
        layout = source_layout(self.page)
        tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
        value, observations, review = read_activity_cell(
            self.page, tokens, self.bounds, identifier=False, native=True, kind="number"
        )
        self.assertEqual(value, "0.4")
        self.assertEqual(observations[0]["method"], "native_cell")
        return observations[0], review

    def payload(self, reading, place="row"):
        if place == "header":
            return {
                "header_observations": {
                    "h": {"page_no": 1, "observations": [{"columns": [reading]}]}
                }
            }
        source = {"page_no": 1, "cells": [{"observations": [reading]}]}
        if place == "unresolved":
            return {"unresolved_rows": [source]}
        return {"rows": [{"activity_sources": [source]}]}

    def check(self, payload):
        return original_activity_source_errors(
            payload, open_original=lambda: nullcontext(self.document)
        )

    def cover(self):
        self.page.draw_rect(fitz.Rect(self.bounds), color=None, fill=(1, 1, 1))

    def test_visible_native_measurement_uses_no_ocr_or_optical_frame(self):
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError("Native readback cannot start OCR"),
        ):
            reading, review = self.reading()
            self.assertFalse(review)
            self.assertNotIn("source_frame", reading)
            self.assertEqual(self.check(self.payload(reading)), [])

    def test_invisible_native_measurement_is_not_qualified_during_capture(self):
        self.cover()
        reading, review = self.reading()
        self.assertTrue(review, "Invisible native values must remain unresolved")
        self.assertTrue(self.check(self.payload(reading)))

    def test_later_cover_rejects_native_headers_values_and_unresolved_cells(self):
        reading, _ = self.reading()
        self.cover()
        for place in ("header", "row", "unresolved"):
            with self.subTest(place=place):
                self.assertTrue(self.check(self.payload(reading, place)))

    def test_missing_original_or_source_profile_cannot_admit_native_observation(self):
        reading, _ = self.reading()
        self.assertTrue(original_activity_source_errors(self.payload(reading)))
        for field in ("source_observation", "bbox"):
            bad = copy.deepcopy(reading)
            del bad[field]
            self.assertTrue(self.check(self.payload(bad)))

    def test_other_cell_text_or_forged_native_profile_cannot_replace_the_original(self):
        reading, _ = self.reading()
        self.page.insert_text((130, 45), "0.4", fontsize=10)
        bad = copy.deepcopy(reading)
        bad["bbox"] = [120, 25, 200, 55]
        self.assertTrue(self.check(self.payload(bad)))
        bad = copy.deepcopy(reading)
        bad["source_observation"]["tokens"][0]["text"] = "0.5"
        self.assertTrue(self.check(self.payload(bad)))

    def test_unrelated_original_drawing_does_not_invalidate_a_visible_cell(self):
        reading, _ = self.reading()
        self.page.draw_rect(fitz.Rect(120, 80, 200, 130), fill=(0, 0, 0))
        self.assertEqual(self.check(self.payload(reading)), [])

    def test_repeated_native_cell_is_replayed_once_without_an_optical_frame(self):
        from patent_sar_extractor.core.native_cell_replay import (
            original_native_cell_matches,
        )

        reading, _ = self.reading()
        payload = self.payload(reading, "header")
        payload.update(self.payload(copy.deepcopy(reading)))
        with patch(
            "patent_sar_extractor.core.activity_auxiliary_replay.original_native_cell_matches",
            wraps=original_native_cell_matches,
        ) as replay:
            self.assertEqual(self.check(payload), [])
            self.assertEqual(replay.call_count, 1)

    def test_history_profile_and_foreign_page_cannot_supply_current_native_proof(self):
        reading, _ = self.reading()
        old = copy.deepcopy(reading)
        old["source_observation"]["schema_version"] = 1
        del old["source_observation"]["boundary_tokens"]
        self.assertTrue(self.check(self.payload(old)))
        foreign = self.payload(reading)
        foreign["rows"][0]["activity_sources"][0]["page_no"] = 2
        self.assertTrue(self.check(foreign))

    def test_native_sources_share_the_existing_bounded_ordinary_inventory(self):
        reading, _ = self.reading()
        other = copy.deepcopy(reading)
        other["bbox"][0] += 1
        payload = self.payload(reading, "header")
        payload.update(self.payload(other))
        with (
            patch(
                "patent_sar_extractor.core.activity_auxiliary_replay.MAX_PRIMARY_SOURCE_CELLS",
                1,
            ),
            self.assertRaisesRegex(ValueError, "bounded inventory"),
        ):
            original_activity_source_errors(payload)

    def test_raster_cell_retains_native_shadow_without_claiming_native_ownership(self):
        from patent_sar_extractor.core.table_cells import (
            _normalize,
            observe_original_cell,
        )

        image = io.BytesIO()
        Image.new("RGB", (240, 160), "white").save(image, format="PNG")
        self.page.insert_image(self.page.rect, stream=image.getvalue(), overlay=False)
        layout = source_layout(self.page)
        observed = [
            {
                "text": "0.4",
                "x": 40,
                "y": 40,
                "bbox": [30, 34, 48, 47],
                "confidence": 0.99,
                "source": "raster",
            }
        ]
        tokens = SourceTokens(observed, layout, layout.raster_bounds)

        def literal(image, *, use_det, use_cls):
            return ([], None) if use_det else ([["0.4", 0.99]], None)

        def optical(page, bounds, kind, dpi):
            return observe_original_cell(page, bounds, kind, dpi, literal, _normalize)

        with patch(
            "patent_sar_extractor.core.table_cells._ocr_cell", side_effect=optical
        ):
            value, readings, review = read_activity_cell(
                self.page, tokens, self.bounds, identifier=False, native=False
            )
        self.assertEqual(value, "0.4")
        self.assertFalse(review)
        shadow = next(item for item in readings if item["method"] == "native_cell")
        self.assertEqual(shadow.get("native_role"), "witness")
        source = {"page_no": 1, "cells": [{"observations": readings}]}
        payload = {"rows": [{"activity_sources": [source]}]}
        self.assertEqual(self.check(payload), [])

    def test_an_independent_native_witness_cannot_be_the_only_measurement_proof(self):
        from patent_sar_extractor.core.activity_metadata import metadata_reading_status
        from patent_sar_extractor.core.activity_result_references import _observed
        from patent_sar_extractor.core.cell_identity_proof import (
            confirmed_identity_readings,
        )

        reading, _ = self.reading()
        reading["native_role"] = "witness"
        cell = {
            "value": "0.4",
            "bbox": self.bounds,
            "raw_header": "n",
            "observations": [reading],
        }
        self.assertFalse(_observed(cell))
        self.assertEqual(metadata_reading_status(cell), "unresolved")
        self.assertFalse(confirmed_identity_readings("1", [{**reading, "text": "1"}]))

    def test_native_witness_role_cannot_be_forged_or_strip_original_provenance(self):
        from patent_sar_extractor.core.source_cell_claims import cell_source_status

        reading, _ = self.reading()
        self.assertEqual(
            cell_source_status({**reading, "native_role": "ignore"}), "invalid"
        )
        bare = {"method": "native_cell", "text": "0.4", "native_role": "witness"}
        self.assertEqual(cell_source_status(bare), "invalid")
