"""Impossible retained constraints stop work, never choose a winning OCR string."""

import copy
import itertools
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.cell_raster import original_reading_image
from patent_sar_extractor.core.text_ocr import recovery_primary
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.source_capture import refine_source_text
from tests import test_auxiliary_cell_evidence as fixture

REFUSAL = {
    "status": "not_attempted",
    "code": "conflicting_retained_primary_claims",
}


class AuxiliaryConflictPreflightTests(unittest.TestCase):
    def setUp(self):
        source = fixture.AuxiliaryCellEvidenceTests()
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.page, self.bounds = source.page, source.bounds
        self.images, self.primaries = source.images, source.primaries

    def conflict(self):
        readings = copy.deepcopy(self.primaries)
        for reading, known in zip(readings, ("HTRF", "TR-FRET"), strict=True):
            reading["parts"][0].update(text=known, confidence=0.99)
            reading["raw_text"] = "\n".join(p["text"] for p in reading["parts"])
        return readings

    def test_direct_complete_pair_refuses_before_any_auxiliary_requests(self):
        readings = self.conflict()
        before = copy.deepcopy(readings)
        reader, attempts = fixture.ControlledAuxiliary(), []
        self.assertIsNone(
            refine_text_pair(self.images, readings, reader, evidence_sink=attempts)
        )
        self.assertEqual(reader.calls, 0)
        self.assertEqual(attempts, [REFUSAL])
        self.assertEqual(readings, before)

    def test_source_refuses_before_runtime_acquisition_or_original_render(self):
        readings = self.conflict()
        before = copy.deepcopy(readings)
        with (
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=fixture.ControlledAuxiliary(),
            ) as acquire,
            patch(
                "patent_sar_extractor.core.cell_raster.original_reading_image",
                wraps=original_reading_image,
            ) as render,
        ):
            selected = refine_source_text(self.page, self.bounds, readings)
        self.assertIs(selected, readings)
        self.assertEqual(acquire.call_count, 0)
        self.assertEqual(render.call_count, 0)
        for previous, reading in zip(before, readings, strict=True):
            self.assertEqual(reading["auxiliary_text_attempts"], [REFUSAL])
            self.assertEqual(
                {k: v for k, v in reading.items() if k != "auxiliary_text_attempts"},
                previous,
            )

    def test_prior_failed_attempts_are_conserved_without_shared_list_mutation(self):
        readings = self.conflict()
        prior = [{"status": "unavailable", "code": "request_timeout"}]
        for reading in readings:
            reading["auxiliary_text_attempts"] = prior
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            return_value=fixture.ControlledAuxiliary(),
        ):
            for _ in range(2):
                refine_source_text(self.page, self.bounds, readings)
        self.assertEqual(prior, [{"status": "unavailable", "code": "request_timeout"}])
        for reading in readings:
            self.assertEqual(reading["auxiliary_text_attempts"], prior + [REFUSAL])
            self.assertIsNot(reading["auxiliary_text_attempts"], prior)

    def test_new_unavailable_attempt_does_not_erase_previous_failure(self):
        class Unavailable:
            def observe(self, image):
                raise TimeoutError("Controlled unavailable reader")

        readings = copy.deepcopy(self.primaries)
        prior = [{"status": "unavailable", "code": "previous_source_failure"}]
        for reading in readings:
            reading["auxiliary_text_attempts"] = prior
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            return_value=Unavailable(),
        ):
            selected = refine_source_text(self.page, self.bounds, readings)
        self.assertIs(selected, readings)
        for reading in readings:
            attempts = reading["auxiliary_text_attempts"]
            self.assertEqual(attempts[0], prior[0])
            self.assertEqual(attempts[1]["code"], "request_timeout")
        self.assertEqual(len(prior), 1)

    def test_weak_and_compatible_fixed_parts_still_recover_through_original_replay(
        self,
    ):
        from patent_sar_extractor.core.text_ocr.cell_proof import replay_auxiliary_cell

        for known in (False, True):
            readings = copy.deepcopy(self.primaries)
            if known:
                for reading in readings:
                    reading["parts"][0].update(text="HTRF", confidence=0.99)
                    reading["raw_text"] = "\n".join(p["text"] for p in reading["parts"])
            reader = fixture.ControlledAuxiliary()
            with self.subTest(known=known):
                recovered = refine_text_pair(self.images, readings, reader)
                self.assertIsNotNone(recovered)
                self.assertEqual(reader.calls, 4)
                self.assertTrue(replay_auxiliary_cell(recovered[0], self.page))

    def test_malformed_attempt_history_refuses_without_discarding_originals(self):
        for invalid in (None, "previous", [None]):
            readings = self.conflict()
            readings[0]["auxiliary_text_attempts"] = invalid
            before = copy.deepcopy(readings)
            with (
                patch(
                    "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime"
                ) as acquire,
                self.assertRaisesRegex(ValueError, "attempt history"),
            ):
                refine_source_text(self.page, self.bounds, readings)
            self.assertEqual(acquire.call_count, 0)
            self.assertEqual(readings, before)


def reading(constraints):
    return {
        "parts": [
            {"text": text, "confidence": score, "confidence_valid": True}
            for text, score in constraints
        ]
    }


class RetainedConstraintProofTests(unittest.TestCase):
    def test_retained_score_boundary_is_shared_with_the_existing_validator(self):
        strong = reading((("A", 0.99),))
        for score, expected in ((0.849999, False), (0.85, True), (0.850001, True)):
            self.assertEqual(
                recovery_primary.primary_constraints_conflict(
                    (strong, reading((("B", score),)))
                ),
                expected,
            )

    def test_preflight_is_only_an_unsatisfiable_existing_constraint_set(self):
        alphabet = tuple(itertools.product(("A", "B"), (0.2, 0.99)))
        vectors = [
            v for count in range(3) for v in itertools.product(alphabet, repeat=count)
        ]
        candidates = [
            v for count in range(3) for v in itertools.product(("A", "B"), repeat=count)
        ]

        def compatible(vector, candidate):
            if len(vector) != len(candidate):
                return not any(score >= 0.85 for _text, score in vector)
            return all(
                score < 0.85 or text == value
                for (text, score), value in zip(vector, candidate)
            )

        conflicts = 0
        for first, second in itertools.product(vectors, repeat=2):
            if recovery_primary.primary_constraints_conflict(
                (reading(first), reading(second))
            ):
                conflicts += 1
                self.assertFalse(
                    any(
                        compatible(first, c) and compatible(second, c)
                        for c in candidates
                    )
                )
        self.assertGreater(conflicts, 0)
        self.assertEqual(len(vectors) ** 2, 441)

    def test_different_counts_conflict_only_if_both_primaries_freeze_a_part(self):
        strong = (("A", 0.99),)
        weak = (("B", 0.2), ("A", 0.2))
        self.assertFalse(
            recovery_primary.primary_constraints_conflict(
                (reading(strong), reading(weak))
            )
        )
        self.assertTrue(
            recovery_primary.primary_constraints_conflict(
                (reading(strong), reading(strong * 2))
            )
        )

    def test_whitespace_and_unknown_parts_do_not_create_known_conflicts(self):
        for first, second in (
            ((("E C50", 0.99),), (("EC50", 0.99),)),
            ((("A", 0.99), ("B", 0.2)), (("B", 0.2), ("A", 0.99))),
        ):
            self.assertFalse(
                recovery_primary.primary_constraints_conflict(
                    (reading(first), reading(second))
                )
            )

    def test_chunked_sources_use_the_same_flattened_part_constraints(self):
        first, second = reading((("A", 0.99),)), reading((("B", 0.99),))
        for source in (first, second):
            source["physical_text_chunks"] = {
                "chunks": [{"reading": {"parts": source.pop("parts")}}]
            }
        self.assertTrue(recovery_primary.primary_constraints_conflict((first, second)))

    def test_malformed_and_unbounded_parts_are_not_classified_as_known_conflicts(self):
        valid = reading((("A", 0.99),))
        bad_score = reading((("B", True),))
        for bad in (
            None,
            [],
            {},
            {"parts": None},
            {"parts": [None]},
            bad_score,
            {"parts": [{"text": "B", "confidence": float("nan")}]},
            {"parts": [{"text": "B", "confidence": 0.99, "confidence_valid": False}]},
            {"parts": [dict(valid["parts"][0])] * (32 * 128 + 1)},
            {"physical_text_chunks": {"chunks": [None]}},
            {"physical_text_chunks": {"chunks": [{"reading": {"parts": [{}] * 33}}]}},
            {"parts": [{"text": "B" * 4097, "confidence": 0.99}]},
        ):
            with self.subTest(bad_type=type(bad).__name__):
                self.assertFalse(
                    recovery_primary.primary_constraints_conflict((valid, bad))
                )

    def test_empty_fixed_text_and_literal_id_differences_stay_frozen(self):
        for first, second in (
            ("", "A"),
            ("I-017", "I-17"),
            ("Compound 8A", "Compound 8B"),
        ):
            self.assertTrue(
                recovery_primary.primary_constraints_conflict(
                    (reading(((first, 0.99),)), reading(((second, 0.99),)))
                )
            )
