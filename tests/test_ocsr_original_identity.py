"""Literal binding identity survives the OCSR runner and image preparation."""

import unittest

from patent_sar_extractor.contracts import STEREO_EVIDENCE_VERSION
from patent_sar_extractor.core.ocsr.label_mask import (
    compound_label as _compound_label_for_ocsr_mask,
)
from patent_sar_extractor.core.ocsr.run_smiles import validate_strict_smiles_results
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import check_source_stereochemistry


class OCSROriginalIdentityTests(unittest.TestCase):
    @staticmethod
    def record(label, structure_id="source-a"):
        checked = qc_smiles("CCO")
        return {
            **checked,
            "cpd_id": label,
            "structure_id": structure_id,
            "raw_smiles": "CCO",
            "image_hash": "a" * 64,
            "OCSR_quality_flag": checked["quality_flag"],
            "OCSR_status": "success",
            "stereochemistry": check_source_stereochemistry(
                checked,
                {
                    "version": STEREO_EVIDENCE_VERSION,
                    "image_sha256": "a" * 64,
                    "image_size": [100, 100],
                    "unknown_bond_boxes": [],
                },
            ),
        }

    def errors(self, expected, actual):
        return validate_strict_smiles_results(
            [{"cpd": expected, "structure_id": "source-a"}],
            [self.record(actual)],
        )

    def test_changed_full_identity_is_rejected_even_for_the_same_image(self):
        for expected, actual in (
            ("Compound 123AB", "Compound 123AC"),
            ("Example 1-2-3", "Example 1-2-4"),
            ("化合物 44AB", "化合物 44AC"),
            ("Compound 0123AB", "Compound 0123A"),
            ("Compound I-73AB", "Compound 73AB"),
        ):
            with self.subTest(expected=expected, actual=actual):
                self.assertTrue(self.errors(expected, actual))

    def test_only_declared_wrapper_case_and_width_equivalence_are_allowed(self):
        for expected, actual in (
            ("Example 123AB", "Cmpd 123ab"),
            ("Compound I-073AB", "化合物 Ｉ－０７３ａｂ"),
            ("Cpd 1-2-3A", "Compound 1-2-3a"),
            ("Claim 1 compound", "CLAIM1"),
        ):
            with self.subTest(expected=expected, actual=actual):
                self.assertEqual(self.errors(expected, actual), [])

    def test_unknown_or_fragmented_identity_cannot_pass_by_matching_itself(self):
        for label in ("", "Compound 1 2", "Compound 44 A", "Compound 8.4", "x" * 129):
            with self.subTest(label=label):
                self.assertTrue(self.errors(label, label))

    def test_duplicate_or_missing_ownership_is_not_a_complete_observation(self):
        binding = {"cpd": "Compound 8", "structure_id": "source-a"}
        record = self.record("Compound 8")
        self.assertTrue(
            validate_strict_smiles_results([binding, binding], [record, record])
        )
        self.assertTrue(validate_strict_smiles_results([{}], [self.record("", "")]))

    def test_mask_candidate_preserves_the_entire_printed_identifier(self):
        for raw, expected in (
            ("Compound 12345AB", "12345AB"),
            ("Example I-073AB", "I-073AB"),
            ("化合物 1-2-3ABC", "1-2-3ABC"),
            ("Cmpd Ｉ－００７ａｂ", "I-007AB"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_compound_label_for_ocsr_mask({"cpd": raw}), expected)

    def test_masking_cannot_borrow_a_partial_or_conflicting_label(self):
        for visible in ("123A", "123AC", "12 3AB", "123AB extra", "123AB²"):
            with self.subTest(visible=visible):
                self.assertEqual(
                    _compound_label_for_ocsr_mask(
                        {"cpd": "Compound 123AB", "visible_label": visible}
                    ),
                    "",
                )
        self.assertEqual(
            _compound_label_for_ocsr_mask(
                {"cpd": "Compound 123AB", "compound_id": "Compound 123AC"}
            ),
            "",
        )

    def test_mask_candidates_must_agree_without_repairing_digits(self):
        self.assertEqual(
            _compound_label_for_ocsr_mask(
                {
                    "cpd": "Example I-073AB",
                    "visible_label": "i-073ab",
                    "visible_label_candidates": [{"label": "Ｉ－０７３ＡＢ"}],
                }
            ),
            "I-073AB",
        )
        self.assertEqual(
            _compound_label_for_ocsr_mask(
                {
                    "cpd": "Compound 73",
                    "visible_label_candidates": [{"label": "73"}, {"label": "7 3"}],
                }
            ),
            "",
        )

    def test_masking_never_mines_an_identifier_from_unknown_prose(self):
        for value in ("Intermediate 73", "formula C12H20N2", "8.4", "label 73", "1 2"):
            with self.subTest(value=value):
                self.assertEqual(_compound_label_for_ocsr_mask({"cpd": value}), "")
