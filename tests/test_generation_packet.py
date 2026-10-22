"""Generated token-sequence bounds and pure completion replay; no model or chemistry repair."""

import copy
import unittest

from patent_sar_extractor.core.ocsr.generation import (
    MAX_GENERATION_TOKENS,
    complete_generation,
    completed_observation,
    observe_generation,
    truncated_observation,
    validate_generated_raw,
    validate_generation,
)


class GenerationPacketTests(unittest.TestCase):
    def test_missing_end_with_an_internal_control_is_not_retryable_truncation(self):
        for token in ("<start>", "<end>", "<pad>", "<unk>"):
            with self.subTest(token=token):
                encoded, packet, _bounds = observe_generation(
                    ["<start>", "C", token, "N"]
                )
                # The SDK's unchanged digit codec maps literal angle brackets.
                # Preserve that raw output; never erase a middle control token.
                raw = encoded.replace("<", "4").replace(">", "5")
                self.assertFalse(
                    truncated_observation(
                        {"status": "failed", "raw_smiles": raw, "generation": packet}
                    )
                )
                self.assertEqual(packet["reason"], "unexpected_special")

    def test_only_literal_failed_missing_end_can_use_existing_retry(self):
        packet = observe_generation(["<start>", "C", "C", "O"])[1]
        row = {"status": "failed", "raw_smiles": "CCO", "generation": packet}
        self.assertTrue(truncated_observation(row))
        for changed in (
            {**row, "status": "timeout"},
            {**row, "status": "unavailable"},
            {**row, "raw_smiles": "CCN"},
            {**row, "generation": None},
            {**row, "generation": {**packet, "status": "complete", "reason": None}},
            {**row, "generation": observe_generation(["C", "C", "O", "<end>"])[1]},
            {
                **row,
                "generation": observe_generation(
                    ["<start>", "C", "<pad>", "O", "<end>"]
                )[1],
            },
            {
                **row,
                "generation": observe_generation(["<start>", "C", "C", "O", "<end>"])[
                    1
                ],
            },
        ):
            with self.subTest(changed=changed):
                self.assertFalse(truncated_observation(changed))

    def test_encoded_atoms_stereo_charge_isotope_and_components_are_verbatim(self):
        words = [
            "<start>",
            "[13C@H+]",
            "(",
            "Cl",
            ")",
            "I",
            ".",
            "N",
            "->",
            "B",
            "<end>",
        ]
        encoded, packet, bounds = observe_generation(words)
        self.assertEqual(encoded, "[13C@H+](Cl)I.N->B")
        self.assertEqual(bounds, (1, len(words) - 1))
        self.assertTrue(validate_generation(packet))
        words[1] = "C"
        self.assertEqual(packet["tokens"][1], "[13C@H+]")

    def test_sdk_digit_alphabet_is_retained_and_raw_decode_is_bound(self):
        words = ["<start>", "C", "!$^<>?£¢€§", "<end>"]
        encoded, packet, _bounds = observe_generation(words)
        self.assertEqual(encoded, "C!$^<>?£¢€§")
        validate_generated_raw(packet, "C1234567890")
        self.assertEqual(packet["tokens"], words)
        for raw in ("CC", encoded, None, 1):
            self.assertFalse(
                completed_observation({"generation": packet, "raw_smiles": raw})
            )

    def test_missing_end_or_start_cannot_be_promoted_by_mutating_a_status_flag(self):
        for words in (["<start>", "C"], ["C", "<end>"]):
            with self.subTest(words=words):
                _encoded, packet, _bounds = observe_generation(words)
                self.assertFalse(validate_generation(packet))
                packet.update(status="complete", reason=None)
                self.assertFalse(complete_generation(packet))
                with self.assertRaises(ValueError):
                    validate_generation(packet)

    def test_reserved_tokens_are_preserved_instead_of_stripped_from_the_middle(self):
        for token in ("<start>", "<end>", "<pad>", "<unk>"):
            with self.subTest(token=token):
                encoded, packet, _bounds = observe_generation(
                    ["<start>", "C", token, "N", "<end>"]
                )
                self.assertEqual(encoded, "C" + token + "N")
                self.assertEqual(packet["reason"], "unexpected_special")
                self.assertFalse(validate_generation(packet))

    def test_exact_count_limit_is_bounded_and_one_more_refuses(self):
        words = ["<start>", *(["C"] * (MAX_GENERATION_TOKENS - 2)), "<end>"]
        _encoded, packet, _bounds = observe_generation(words)
        self.assertTrue(validate_generation(packet))
        with self.assertRaises(ValueError):
            observe_generation([*words[:-1], "C", "<end>"])

    def test_total_text_limit_does_not_depend_only_on_token_count(self):
        with self.assertRaises(ValueError):
            observe_generation(["<start>", *(["C" * 32] * 400), "<end>"])

    def test_malformed_unbounded_or_non_text_tokens_refuse(self):
        for words in (
            None,
            "CCO",
            (),
            [],
            [True],
            [1],
            [None],
            [""],
            ["C" * 33],
            ["C\n"],
            ["λ"],
        ):
            with self.subTest(words=words), self.assertRaises(ValueError):
                observe_generation(words)

    def test_unknown_or_boolean_versions_and_extra_fields_refuse(self):
        _encoded, packet, _bounds = observe_generation(["<start>", "C", "<end>"])
        for changed in (
            {**packet, "version": True},
            {**packet, "version": 2},
            {**packet, "accepted": True},
            {},
        ):
            self.assertFalse(complete_generation(changed))

    def test_validating_a_record_never_mutates_its_original_tokens(self):
        _encoded, packet, _bounds = observe_generation(["<start>", "C", "<end>"])
        before = copy.deepcopy(packet)
        self.assertTrue(validate_generation(packet))
        self.assertEqual(packet, before)
