"""Pure synthetic candidate guards; no model, image or private molecular fixture."""

from __future__ import annotations

import unittest
from time import monotonic
from unittest.mock import patch

from patent_sar_extractor.contracts import STEREO_EVIDENCE_VERSION
from patent_sar_extractor.core.ocsr import stereo_rescue
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import source_checked_qc

PARTIAL = "C[C@H]1CC(C)(O)C1"
PAIRED = "C[C@H]1C[C@](C)(O)C1"
FLAG = "stereochemistry_not_retained"


class StereoRescueTests(unittest.TestCase):
    def validate(self, primary=PARTIAL, candidate=PAIRED, **limits):
        return stereo_rescue.validate_stereo_rescue(
            primary, candidate, primary_quality_flag=FLAG, **limits
        )

    def assert_rejected(self, primary=PARTIAL, candidate=PAIRED, reason=None, **limits):
        result = self.validate(primary, candidate, **limits)
        self.assertFalse(result["accepted"])
        if reason is not None:
            self.assertEqual(result["reason"], reason)
        return result

    def test_only_the_exact_primary_quality_flag_is_eligible(self):
        self.assertTrue(stereo_rescue.stereo_rescue_eligible(FLAG))
        for flag in (
            "ok",
            "invalid_smiles",
            "stereo_source_conflict",
            "unsupported_stereochemistry",
            "markush_or_query",
            "stereochemistry_not_retained ",
            None,
            True,
            {},
        ):
            with self.subTest(flag=flag):
                self.assertFalse(stereo_rescue.stereo_rescue_eligible(flag))

    def test_good_primary_does_not_even_inspect_candidate_or_call_qc(self):
        with patch.object(stereo_rescue, "qc_smiles") as qc:
            result = stereo_rescue.validate_stereo_rescue(
                "c1ccccc1", object(), primary_quality_flag="ok"
            )
        self.assertFalse(result["eligible"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "primary_not_eligible")
        qc.assert_not_called()

    def test_supplied_flag_does_not_override_actual_primary_qc(self):
        result = self.assert_rejected("CCO", PAIRED, "primary_quality_mismatch")
        self.assertFalse(result["eligible"])

    def test_partial_one_three_ring_can_retain_both_marked_centers(self):
        self.assertEqual(qc_smiles(PARTIAL)["quality_flag"], FLAG)
        self.assertEqual(qc_smiles(PAIRED)["assigned_chiral_centers"], 2)
        result = self.validate()
        self.assertTrue(result["eligible"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["reason"], "compatible_stereo_candidate")
        self.assertGreater(result["mappings_checked"], 1)
        self.assertEqual(
            set(result), {"eligible", "accepted", "reason", "mappings_checked"}
        )
        self.assertEqual(PARTIAL, "C[C@H]1CC(C)(O)C1")
        self.assertEqual(PAIRED, "C[C@H]1C[C@](C)(O)C1")

    def test_atom_order_change_preserves_retained_primary_cip(self):
        primary = "N[C@@H](F)C[C@H]1CC(C)(O)C1"
        candidate = "C[C@]1(O)C[C@H](C[C@@H](N)F)C1"
        self.assertEqual(qc_smiles(primary)["assigned_chiral_centers"], 1)
        self.assertTrue(self.validate(primary, candidate)["accepted"])

    def test_retained_primary_center_cannot_flip(self):
        self.assert_rejected(
            "N[C@@H](F)C[C@H]1CC(C)(O)C1",
            "N[C@H](F)C[C@H]1C[C@](C)(O)C1",
            "retained_atom_stereo_conflict",
        )

    def test_retained_ez_survives_traversal_change_but_cannot_flip(self):
        primary = "F/C=C/C[C@H]1CC(C)(O)C1"
        candidate = "C[C@]1(O)C[C@H](C/C=C/F)C1"
        self.assertTrue(self.validate(primary, candidate)["accepted"])
        self.assert_rejected(
            primary, "F/C=C\\C[C@H]1C[C@](C)(O)C1", "retained_bond_stereo_conflict"
        )

    def test_retained_ez_cannot_disappear(self):
        self.assert_rejected(
            "F/C=C/C[C@H]1CC(C)(O)C1",
            "FC=CC[C@H]1C[C@](C)(O)C1",
            "raw_stereo_tokens_dropped",
        )

    def test_all_nonstereo_graph_attributes_and_fragments_must_match(self):
        cases = (
            (PARTIAL, "C[C@H]1C[C@](C)(N)C1", "element"),
            (PARTIAL, "C[C@H]1CC[C@](C)(O)C1", "added_atom"),
            (PARTIAL, "C[C@H](O)[C@H](C)CC", "connectivity"),
            (PARTIAL + ".C=C", PAIRED + ".CC", "bond_order"),
            (PARTIAL + ".[13CH3]CO", PAIRED + ".[12CH3]CO", "isotope"),
            (PARTIAL + ".[NH4+]", PAIRED + ".N", "charge"),
            (PARTIAL + ".O", PAIRED, "dropped_fragment"),
            (PARTIAL + ".C", "C[C@H]1C[C@](C)(OC)C1", "merged_fragment"),
        )
        for primary, candidate, kind in cases:
            with self.subTest(kind=kind):
                self.assertEqual(qc_smiles(candidate)["quality_flag"], "ok")
                self.assert_rejected(primary, candidate, "graph_mismatch")

    def test_isotopic_hydrogens_charge_and_fragment_order_are_preserved(self):
        primary = PARTIAL + ".[2H]O[2H].[Na+]"
        candidate = "[Na+].[2H]O[2H]." + PAIRED
        self.assertTrue(self.validate(primary, candidate)["accepted"])

    def test_removing_raw_stereo_is_not_a_rescue(self):
        self.assert_rejected(PARTIAL, "CC1CC(C)(O)C1", "raw_stereo_tokens_dropped")

    def test_new_stereo_elsewhere_cannot_replace_the_raw_marked_site(self):
        self.assert_rejected(
            "NC(F)C." + PARTIAL,
            "N[C@@H](F)C.CC1CC(C)(O)C1",
            "raw_stereo_not_restored",
        )

    def test_candidate_must_be_clean_and_canonical_markup_lossless(self):
        self.assert_rejected(PARTIAL, PARTIAL, "candidate_not_clean")
        candidate = "F/C=C(/Cl)\\Br." + PAIRED
        primary = "FC=C(Cl)Br." + PARTIAL
        self.assertEqual(qc_smiles(candidate)["quality_flag"], "ok")
        self.assert_rejected(primary, candidate, "candidate_markup_not_retained")

    def test_retained_stereo_can_resolve_competing_nonstereo_mappings(self):
        result = self.validate(
            "N[C@@H](F)C.N[C@H](F)C." + PARTIAL,
            "N[C@@H](F)C.N[C@H](F)C." + PAIRED,
        )
        self.assertTrue(result["accepted"])
        self.assertGreater(result["mappings_checked"], 1)

    def test_remaining_stereo_assignments_must_agree_after_retained_constraints(self):
        self.assert_rejected(
            "N[C@@H](F)C." + PARTIAL + "." + PARTIAL,
            "N[C@@H](F)C." + PAIRED + ".C[C@H]1C[C@@](C)(O)C1",
            "ambiguous_stereo_mapping",
        )

    def test_distinct_stereo_placements_under_symmetric_maps_are_ambiguous(self):
        self.assert_rejected(
            PARTIAL + "." + PARTIAL,
            PAIRED + ".C[C@H]1C[C@@](C)(O)C1",
            "ambiguous_stereo_mapping",
        )

    def test_unmarked_centers_cannot_be_assigned_in_connected_or_separate_fragments(
        self,
    ):
        cases = (
            ("NC(F)C." + PARTIAL, "N[C@@H](F)C." + PAIRED),
            ("NC(F)C" + PARTIAL, "N[C@@H](F)C" + PAIRED),
            (PARTIAL + ".CC1CC(C)(O)C1", PAIRED + ".C[C@H]1C[C@](C)(O)C1"),
        )
        for primary, candidate in cases:
            with self.subTest(primary=primary):
                self.assertEqual(qc_smiles(primary)["quality_flag"], FLAG)
                self.assertEqual(qc_smiles(candidate)["quality_flag"], "ok")
                self.assert_rejected(primary, candidate, "unrelated_atom_stereo")

    def test_originally_oh_marked_ring_can_add_its_indispensable_counterpart(self):
        primary = "CC1C[C@](C)(O)C1"
        self.assertEqual(qc_smiles(primary)["quality_flag"], FLAG)
        self.assertTrue(self.validate(primary, PAIRED)["accepted"])

    def test_unencoded_double_bond_stereo_cannot_be_added(self):
        self.assert_rejected(
            "FC=CC." + PARTIAL, "F/C=C/C." + PAIRED, "unrequested_bond_stereo"
        )

    def test_lost_nonring_stereo_remains_review_needed(self):
        primary = "C[C@H](CC(O)C)CC(O)C"
        candidate = "C[C@H](C[C@H](O)C)C[C@@H](O)C"
        self.assertEqual(qc_smiles(primary)["quality_flag"], FLAG)
        self.assertEqual(qc_smiles(candidate)["quality_flag"], "ok")
        self.assert_rejected(primary, candidate, "unsupported_lost_stereo")

    def test_same_ring_membership_alone_does_not_make_extra_stereo_necessary(self):
        primary = "C[C@H]1C(C)C(C)(O)C(C)1"
        candidate = "C[C@H]1[C@H](C)[C@](C)(O)[C@H](C)1"
        self.assertEqual(qc_smiles(primary)["quality_flag"], FLAG)
        self.assertEqual(qc_smiles(candidate)["quality_flag"], "ok")
        self.assert_rejected(primary, candidate, "nonessential_ring_stereo")

    def test_counterfactual_validation_does_not_mutate_either_observed_molecule(self):
        deadline = monotonic() + 1
        primary, _ = stereo_rescue._observe("CC1C[C@](C)(O)C1", deadline)
        candidate, _ = stereo_rescue._observe(PAIRED, deadline)

        def snapshot(graph):
            return tuple(
                (
                    a.GetChiralTag(),
                    tuple(
                        (name, a.GetProp(name))
                        for name in a.GetPropNames(
                            includePrivate=True, includeComputed=True
                        )
                        if name != "__computedProps"
                    ),
                )
                for a in graph.mol.GetAtoms()
            )

        before = snapshot(primary), snapshot(candidate)
        self.assertGreater(
            stereo_rescue._all_mappings(primary, candidate, deadline, 64, 20000), 1
        )
        self.assertEqual(before, (snapshot(primary), snapshot(candidate)))

    def test_mapping_and_search_bounds_refuse_without_selecting_a_first_match(self):
        result = self.assert_rejected(reason="mapping_budget_exceeded", max_mappings=1)
        self.assertEqual(result["mappings_checked"], 1)
        self.assert_rejected(reason="search_budget_exceeded", max_search_states=1)

    def test_size_bounds_are_checked_before_qc(self):
        for primary in ("C" * 5000, "C" * 129 + "." + PARTIAL, PARTIAL + ".C" * 8):
            with (
                self.subTest(length=len(primary)),
                patch.object(stereo_rescue, "qc_smiles") as qc,
            ):
                self.assert_rejected(primary, reason="input_budget_exceeded")
                qc.assert_not_called()
        with patch.object(stereo_rescue, "MAX_BONDS", 2):
            self.assert_rejected(reason="input_budget_exceeded")

    def test_invalid_limits_and_expired_time_budget_refuse(self):
        for limits in (
            {"timeout_seconds": 0},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": float("inf")},
            {"timeout_seconds": True},
            {"max_mappings": 0},
            {"max_mappings": 65},
            {"max_search_states": 0},
            {"max_search_states": True},
        ):
            with self.subTest(limits=limits):
                self.assert_rejected(reason="invalid_budget", **limits)
        with patch.object(stereo_rescue, "monotonic", side_effect=[0.0, 1.0]):
            self.assert_rejected(reason="time_budget_exceeded")

    def test_unsupported_or_malformed_inputs_never_acquire_acceptance(self):
        for candidate in (
            None,
            b"CC",
            1,
            "",
            "not-a-smiles",
            PAIRED + " |o1:1|",
            " " + PAIRED,
            PAIRED + "\n",
            "[CH3:7][C@H]1C[C@](C)(O)C1",
            "C[C@TH1H]1C[C@](C)(O)C1",
            "*" + PAIRED,
            PAIRED + ".[CH3]",
            PAIRED + ".[O-]->[Na+]",
        ):
            with self.subTest(candidate=candidate):
                self.assert_rejected(candidate=candidate)
        self.assert_rejected("C/C", "CC")

    def test_native_cip_failure_or_unexpected_qc_error_is_fail_closed(self):
        with patch.object(
            stereo_rescue.rdCIPLabeler, "AssignCIPLabels", side_effect=RuntimeError
        ):
            self.assert_rejected(reason="cip_assignment_failed")
        with patch.object(stereo_rescue, "qc_smiles", side_effect=RuntimeError):
            self.assert_rejected(reason="validation_failed")

    def test_cip_work_is_bounded_and_guard_cannot_override_source_qc(self):
        native = stereo_rescue.rdCIPLabeler.AssignCIPLabels
        with patch.object(
            stereo_rescue.rdCIPLabeler, "AssignCIPLabels", wraps=native
        ) as cip:
            self.assertTrue(self.validate()["accepted"])
        self.assertTrue(cip.call_args_list)
        self.assertTrue(
            all(
                call.kwargs["maxRecursiveIterations"]
                == stereo_rescue.MAX_CIP_ITERATIONS
                for call in cip.call_args_list
            )
        )
        result = source_checked_qc(
            qc_smiles(PAIRED),
            {
                "version": STEREO_EVIDENCE_VERSION,
                "image_sha256": "b" * 64,
                "image_size": [100, 100],
                "unknown_bond_boxes": [[10, 10, 30, 30]],
            },
        )
        self.assertIn(
            result["quality_flag"],
            {"stereo_source_conflict", "stereo_source_ambiguous"},
        )
        self.assertFalse(result["stereochemistry"]["absolute_configuration_verified"])


if __name__ == "__main__":
    unittest.main()
