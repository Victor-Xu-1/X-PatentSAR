"""Original native/qualified claims and unqualified raster hints stay distinct."""

import copy
import unittest
from unittest.mock import Mock, patch

import fitz
from header_support import observed_headers

from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.activity_result_references import _observed
from patent_sar_extractor.core.cell_identity_proof import (
    confirmed_identity_readings as _confirmed_observations,
)
from patent_sar_extractor.core.cell_ocr_observation import OCRObservation
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.core.table_cells import read_cell


def token(text, confidence, x=110, y=110):
    return {
        "text": text,
        "confidence": confidence,
        "x": x,
        "y": y,
        "bbox": [x - 15, y - 4, x + 15, y + 4],
        "source": "raster",
        "geometry_space": "rendered",
    }


def source_tokens(parts, native=()):
    return SourceTokens(
        parts, SourceLayout(tuple(native), (0, 0, 500, 600)), (0, 0, 500, 600)
    )


class SourceHintAuthorityTests(unittest.TestCase):
    def test_weak_scalar_hint_does_not_replace_the_two_owned_cell_observations(self):
        tokens = source_tokens([token("10 nM", 0.2)])
        with patch(
            "patent_sar_extractor.core.table_cells._ocr_cell",
            return_value=OCRObservation("8 nM", 0.99, "8 nM"),
        ):
            value, observations, review = read_activity_cell(
                Mock(), tokens, (70, 95, 160, 130), identifier=False, native=False
            )
        self.assertEqual(value, "8 nM")
        self.assertFalse(review)
        self.assertTrue(
            _observed(
                {
                    "field": "IC50 (nM)",
                    "value": value,
                    "observations": observations,
                    "bbox": [70, 95, 160, 130],
                }
            )
        )

    def caption(self, text, confidence, *, native=()):
        observed = source_tokens([token(text, confidence)], native)
        with patch(
            "patent_sar_extractor.core.table_cells._ocr_cell",
            return_value=OCRObservation("42", 0.99, "Compound 42"),
        ) as reader:
            result = read_cell(Mock(), (70, 95, 160, 130), observed, "label", False)
        return result, reader.call_count

    def test_weak_raster_identifier_is_a_hint_not_a_valid_competing_identity(self):
        reading, count = self.caption("Compound 43", 0.2)
        self.assertEqual(reading.value, "42", reading.observations)
        self.assertFalse(reading.needs_review)
        self.assertEqual(count, 2)
        original = reading.observations[0]
        self.assertEqual(original["text"], "Compound 43")
        self.assertEqual(original["source_observation"]["status"], "unqualified")
        self.assertTrue(
            _confirmed_observations("42", reading.observations, caption=True)
        )

    def test_a_matching_weak_hint_cannot_substitute_for_second_owned_source_read(self):
        reading, count = self.caption("Compound 42", 0.2)
        self.assertEqual(count, 2)
        self.assertFalse(reading.needs_review)

    def test_qualified_page_identity_and_native_shadow_cannot_be_outvoted(self):
        reading, _ = self.caption("Compound 43", 0.99)
        self.assertTrue(reading.needs_review)
        self.assertEqual(reading.value, "")
        native = {**token("Compound 43", 1), "source": "native"}
        reading, _ = self.caption("Compound 42", 0.2, native=[native])
        self.assertTrue(reading.needs_review)
        self.assertFalse(
            _confirmed_observations("42", reading.observations, caption=True)
        )

    def test_saved_hint_flags_cannot_override_the_retained_qualified_source(self):
        reading, _ = self.caption("Compound 43", 0.2)
        changed = copy.deepcopy(reading.observations)
        changed[0]["source_observation"]["tokens"][0]["confidence"] = 0.99
        self.assertFalse(_confirmed_observations("42", changed, caption=True))

    def header(self, confidence):
        region = {"xs": [40, 90, 220], "ys": [100, 140, 170]}
        old, fresh = "TargetA IC50 (uM)", "TargetB IC50 (nM)"
        parts = [token("No.", 0.99, 65, 120), token(old, confidence, 150, 120)]
        original = grid_schema(
            context_from_text("Table 7. Binding assay"), [["No.", old]]
        )
        page = Mock(rect=fitz.Rect(0, 0, 500, 600))
        page.get_text.return_value = []
        with (
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.observe_header_columns",
                side_effect=lambda page, region, limit, dpi, tokens: observed_headers(
                    [["No.", fresh]], region, limit, dpi
                ),
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation._prefix",
                return_value="Table 7. Binding assay",
            ),
        ):
            return refine_scanned_header(
                page, region, original, tokens=source_tokens(parts)
            )

    def test_weak_header_locator_cannot_claim_a_known_target_or_unit(self):
        observed = self.header(0.2)
        self.assertEqual(observed.raw_headers[1], "TargetB IC50 (nM)")
        self.assertTrue(valid_header_proof(observed.header_resolution))
        self.assertEqual(
            observed.header_resolution["original_headers"][1], "TargetA IC50 (uM)"
        )

    def test_qualified_header_source_conflict_still_refuses_consensus(self):
        observed = self.header(0.99)
        self.assertEqual(observed.header_resolution["status"], "unresolved")
        self.assertFalse(valid_header_proof(observed.header_resolution))
