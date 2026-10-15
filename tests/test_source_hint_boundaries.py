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
from patent_sar_extractor.core.activity_header_sources import (
    _context_conflict,
    select_header_context,
)
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.activity_result_references import _observed
from patent_sar_extractor.core.cell_ocr_observation import OCRObservation
from patent_sar_extractor.core.numbered_structure_pairs import _confirmed_observations
from patent_sar_extractor.core.source_observations import (
    source_cell_observation,
    source_claim_runs,
    source_observation_status,
)
from patent_sar_extractor.core.table_cells import cell_image

BOUNDS = (70, 95, 200, 130)


class SourceHintBoundaryTests(unittest.TestCase):
    def test_complete_native_context_can_survive_a_shorter_raster_observation(self):
        parts = [
            {**token("Table 7. Binding activity", 1, 50, 80), "source": "native"},
            {**token("Target: JAK2", 1, 100, 90), "source": "native"},
        ]
        observed = source_tokens([token("Noise", 0.2, 150, 95)], parts)
        bounds = (0, 0, 500, 100)
        selected = select_header_context(
            {
                "prefix": source_cell_observation(observed, bounds),
                "native_prefix": source_cell_observation(observed, bounds, native=True),
            },
            [40, 100, 220, 140],
            context_from_text("Table 7. Binding activity"),
        )
        self.assertEqual(selected.target, "JAK2")
        self.assertEqual(
            selected.raw_context, "Table 7. Binding activity\nTarget: JAK2"
        )

    def test_known_condition_cannot_disappear_inside_an_incomplete_source_window(self):
        parts = [
            token("Table 7. Binding activity", 0.99, 50, 80),
            token("Target: JAK2", 0.99, 100, 90),
            token("Unclear source text", 0.2, 150, 95),
        ]
        packet = source_cell_observation(source_tokens(parts), (0, 0, 500, 100))
        self.assertIsNone(
            select_header_context(
                {"prefix": packet},
                [40, 100, 220, 140],
                context_from_text("Table 7. Binding activity"),
            )
        )

    def test_weak_earlier_table_words_do_not_cross_a_proved_new_caption(self):
        parts = [
            token("Table 17. Characterization", 0.99, 50, 80),
            token("Unclear characterization", 0.2, 150, 130),
            token("Table 88. Binding activity", 0.99, 50, 350),
        ]
        bounds = (0, 65, 500, 375)
        fresh = context_from_text("Table 88. Binding activity")
        packet = source_cell_observation(source_tokens(parts), bounds)
        self.assertEqual(packet["status"], "unqualified")
        self.assertFalse(_context_conflict(packet, fresh, {"xs": [40], "ys": [375]}))
        self.assertTrue(
            _context_conflict(
                packet,
                context_from_text("Table 99. Binding activity"),
                {"xs": [40], "ys": [375]},
            )
        )
        weak_boundary = [{**part} for part in parts]
        weak_boundary[-1]["confidence"] = 0.2
        packet = source_cell_observation(source_tokens(weak_boundary), bounds)
        self.assertTrue(_context_conflict(packet, fresh, {"xs": [40], "ys": [375]}))

    def test_oversized_native_blank_check_is_bounded_before_pixel_allocation(self):
        page = Mock(rect=fitz.Rect(0, 0, 10000, 10000))
        page.get_pixmap.side_effect = AssertionError("Raster allocation was attempted")
        with self.assertRaisesRegex(ValueError, "pixel budget"):
            cell_image(page, (10, 10, 9000, 9000), 400)
        page.get_pixmap.assert_not_called()

    def test_original_controls_keep_literal_identity_not_a_compound_number(self):
        for label in ("Ref. 1", "Ref 2", "Vehicle", "DMSO", "Control"):
            native = {**token(label, 1), "source": "native"}
            observations = [
                {
                    "method": "native_cell",
                    "text": label,
                    "bbox": list(BOUNDS),
                    "source_observation": source_cell_observation(
                        source_tokens([native], [native]), BOUNDS, native=True
                    ),
                }
            ]
            cell = {
                "field": "compound_id",
                "value": label,
                "bbox": list(BOUNDS),
                "observations": observations,
            }
            with self.subTest(label=label):
                self.assertTrue(_observed(cell, identifier=True))
                self.assertFalse(_confirmed_observations(label, observations))
                for replacement in ("Ref. 3", "Compound 1"):
                    self.assertFalse(
                        _observed({**cell, "value": replacement}, identifier=True)
                    )

    def test_control_identity_never_waives_source_scope_or_invalid_confidence(self):
        native = {**token("Ref. 1", 1), "source": "native"}
        observation = {
            "method": "native_cell",
            "text": "Ref. 1",
            "bbox": list(BOUNDS),
            "source_observation": source_cell_observation(
                source_tokens([native], [native]), BOUNDS, native=True
            ),
        }
        cell = {
            "field": "compound_id",
            "value": "Ref. 1",
            "bbox": list(BOUNDS),
            "observations": [observation],
        }
        moved = copy.deepcopy(cell)
        moved["observations"][0]["bbox"][0] += 1
        self.assertFalse(_observed(moved, identifier=True))
        invalid = copy.deepcopy(cell)
        invalid["observations"][0]["source_observation"]["tokens"][0]["confidence"] = (
            True
        )
        self.assertFalse(_observed(invalid, identifier=True))

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

    def test_qualified_decimal_sign_and_censoring_are_not_erased_by_a_weak_hint(self):
        for raw, candidate in (
            ("1.0 nM", "10 nM"),
            ("-1 nM", "1 nM"),
            ("<10 nM", "<8 nM"),
            ("1 ± 0.2 nM", "1 ± 0.3 nM"),
        ):
            observed = source_tokens([token("Noise", 0.2, 95), token(raw, 0.99, 150)])
            with (
                self.subTest(raw=raw, candidate=candidate),
                patch(
                    "patent_sar_extractor.core.table_cells._ocr_cell",
                    return_value=OCRObservation(candidate, 0.99, candidate),
                ),
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
