"""Adversarial source-role, value, geometry and saved-proof boundary cases."""

import copy
import unittest
from unittest.mock import Mock, patch

import fitz
from header_support import observed_headers
from test_source_hint_authority import SourceHintAuthorityTests, source_tokens, token

from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.cell_ocr_observation import OCRObservation
from patent_sar_extractor.core.numbered_structure_pairs import _confirmed_observations
from patent_sar_extractor.core.source_observations import (
    source_cell_observation,
    source_claim_runs,
    source_observation_status,
)

BOUNDS = (70, 95, 200, 130)


class SourceHintBoundaryTests(unittest.TestCase):
    def test_shorter_header_reread_cannot_drop_known_target_and_cell_line(self):
        raw = "Table 7. Binding assay\nTarget: JAK2\nHEK293 cells"
        region = {"xs": [40, 90, 220], "ys": [100, 140, 170]}
        original = grid_schema(context_from_text(raw, raw), [["No.", "IC50 (nM)"]])
        parts = [
            token("Table 7. Binding assay", 0.99, 50, 65),
            token("Target: JAK2", 0.99, 75, 75),
            token("HEK293 cells", 0.99, 75, 85),
            token("No.", 0.99, 65, 120),
            token("IC50 (nM)", 0.99, 150, 120),
        ]
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
                    [["No.", "IC50 (nM)"]], region, limit, dpi
                ),
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation._prefix",
                return_value="Table 7. Binding assay",
            ),
        ):
            result = refine_scanned_header(
                page, region, original, tokens=source_tokens(parts)
            )
        self.assertEqual(result.context.target, "JAK2")
        self.assertEqual(result.context.cell_line, "HEK293")
        self.assertEqual(
            result.header_resolution["status"], "observed_header_consensus"
        )

    def test_qualified_value_and_unit_fragments_both_survive_a_weak_neighbor(self):
        observed = source_tokens([token("Noise", 0.2, 95), token("10 nM", 0.99, 150)])
        with patch(
            "patent_sar_extractor.core.table_cells._ocr_cell",
            return_value=OCRObservation("8 nM", 0.99, "8 nM"),
        ):
            _value, _proof, review = read_activity_cell(
                Mock(), observed, BOUNDS, identifier=False, native=False
            )
        self.assertTrue(review)

    def test_weak_role_hint_is_not_reinterpreted_after_saving(self):
        fixture = SourceHintAuthorityTests()
        reading, _ = fixture.caption("Intermediate 43", 0.2)
        self.assertEqual(reading.value, "42")
        self.assertFalse(reading.needs_review)
        self.assertTrue(
            _confirmed_observations("42", reading.observations, caption=True)
        )

    def test_current_source_proof_cannot_be_downgraded_to_ignore_original_sources(self):
        proof = copy.deepcopy(SourceHintAuthorityTests().header(0.2).header_resolution)
        proof["column_contract"] = 1
        proof["original_headers"] = []
        proof["original_context"] = ""
        self.assertFalse(valid_header_proof(proof))

    def test_packet_flags_geometry_and_score_types_are_rechecked(self):
        packet = source_cell_observation(
            source_tokens([token("Compound 43", 0.2)]), BOUNDS
        )
        for key, value in (
            ("status", "qualified"),
            ("schema_version", True),
            ("origin", "native"),
        ):
            changed = copy.deepcopy(packet)
            changed[key] = value
            with self.subTest(key=key):
                self.assertEqual(
                    source_observation_status(changed, BOUNDS, packet["text"]),
                    "invalid",
                )
        for score in (True, "0.99", float("nan"), float("inf")):
            changed = copy.deepcopy(packet)
            changed["tokens"][0]["confidence"] = score
            with self.subTest(score=score):
                self.assertEqual(
                    source_observation_status(changed, BOUNDS, packet["text"]),
                    "invalid",
                )

    def test_claim_runs_follow_physical_order_without_bridging_a_weak_word(self):
        packet = source_cell_observation(
            source_tokens(
                [
                    token("nM", 0.99, 180),
                    token("TargetA", 0.99, 95),
                    token("IC50", 0.2, 140),
                ]
            ),
            BOUNDS,
        )
        self.assertEqual(source_claim_runs(packet), (("TargetA",), ("nM",)))
