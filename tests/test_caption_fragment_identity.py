"""Literal fragment agreement is ordered and includes printed prefix/suffix."""

import json
import unittest

from patent_sar_extractor.core.cell_caption_identity import refined_caption_conflicts


def fragment(text, index, confidence=0.99, top=8):
    left = 8 + index * 55
    return {
        "text": text,
        "confidence": confidence,
        "bbox": [[left, top], [left + 45, top], [left + 45, 42], [left, 42]],
        "coordinate_space": "cell_ink_crop_pixels",
    }


def complete(label, raw=None):
    return [
        {
            **fragment(raw or f"Compound {label}", 0),
            "method": "complete_line_recognition",
        }
    ]


class CaptionFragmentIdentityTests(unittest.TestCase):
    @staticmethod
    def overlapping_role_and_suffix(role="Compound", label="935AB"):
        parts = [
            fragment(role[:1], 0),
            fragment(role, 1),
            fragment(label[:-1], 2),
            fragment(label[-2:], 3),
        ]
        for part, (left, right) in zip(
            parts, ((2, 28), (14, 142), (132, 210), (194, 238)), strict=True
        ):
            part["bbox"] = [[left, 8], [right, 8], [right, 48], [left, 48]]
        return parts

    def test_overlapping_role_glyph_and_id_boundary_preserve_the_complete_literal(self):
        for role, label in (
            ("Compound", "935AB"),
            ("Example", "81YZ"),
            ("Cmpd", "64AB"),
        ):
            with self.subTest(role=role, label=label):
                packet = json.loads(
                    json.dumps(self.overlapping_role_and_suffix(role, label))
                )
                self.assertFalse(
                    refined_caption_conflicts(
                        label, complete(label, f"{role} {label}"), packet
                    )
                )

    def test_overlapping_literal_projection_cannot_hide_a_different_or_separate_glyph(
        self,
    ):
        original = self.overlapping_role_and_suffix()
        for index, update in (
            (0, {"text": "D"}),
            (0, {"bbox": [[2, 55], [28, 55], [28, 88], [2, 88]]}),
            (0, {"bbox": [[0, 8], [10, 8], [10, 48], [0, 48]]}),
            (1, {"confidence": 0.84}),
            (3, {"text": "AC"}),
            (3, {"bbox": [[220, 8], [255, 8], [255, 48], [220, 48]]}),
            (3, {"bbox": [[150, 8], [180, 8], [180, 48], [150, 48]]}),
        ):
            changed = json.loads(json.dumps(original))
            changed[index].update(update)
            with self.subTest(index=index, update=update):
                self.assertTrue(
                    refined_caption_conflicts("935AB", complete("935AB"), changed)
                )

    def test_a_repeated_letter_inside_a_qualified_whole_id_box_is_not_an_extra_suffix(
        self,
    ):
        for label in ("R-052C", "47A", "AB-003Z"):
            with self.subTest(label=label):
                original = [
                    fragment("Compound", 0),
                    fragment(label, 1),
                    fragment(label[-1], 2),
                ]
                original[0]["bbox"] = [[0, 8], [65, 8], [65, 42], [0, 42]]
                original[1]["bbox"] = [[100, 8], [190, 8], [190, 42], [100, 42]]
                original[2]["bbox"] = [[155, 8], [205, 8], [205, 42], [155, 42]]
                self.assertFalse(
                    refined_caption_conflicts(label, complete(label), original)
                )
                for text, box in (
                    ("D", original[2]["bbox"]),
                    (label[-1], [[210, 8], [240, 8], [240, 42], [210, 42]]),
                    (label[-1], [[155, 50], [190, 50], [190, 80], [155, 80]]),
                ):
                    changed = json.loads(json.dumps(original))
                    changed[2].update(text=text, bbox=box)
                    self.assertTrue(
                        refined_caption_conflicts(label, complete(label), changed)
                    )

    def test_literal_hyphenated_parts_are_not_independent_complete_identifiers(self):
        for label, words in (
            ("Q-028C", ("Compound", "Q", "-028C")),
            ("AB-093", ("Compound", "AB", "-093")),
        ):
            with self.subTest(label=label):
                self.assertFalse(
                    refined_caption_conflicts(
                        label,
                        complete(label),
                        [fragment(word, index) for index, word in enumerate(words)],
                    )
                )

    def test_hyphen_fragment_cannot_remove_zeros_or_change_letters_or_digits(self):
        for suffix in ("-28C", "-028D", "-029C", "-028C/1"):
            with self.subTest(suffix=suffix):
                self.assertTrue(
                    refined_caption_conflicts(
                        "Q-028C",
                        complete("Q-028C"),
                        [
                            fragment("Compound", 0),
                            fragment("Q", 1),
                            fragment(suffix, 2),
                        ],
                    )
                )

    def test_correct_literal_fragments_keep_suffixes_and_leading_zeros(self):
        for label, words in (
            ("47", ("Compound", "4", "7")),
            ("47A", ("Compound", "4", "7", "A")),
            ("I-47", ("Compound", "I-", "4", "7")),
            ("047", ("Com", "pound", "0", "4", "7")),
            ("0047", ("Compound", "0", "0", "4", "7")),
        ):
            with self.subTest(label=label):
                self.assertFalse(
                    refined_caption_conflicts(
                        label,
                        complete(label),
                        [fragment(word, index) for index, word in enumerate(words)],
                    )
                )

    def test_separate_letter_or_series_prefix_conflicts_are_not_ignored(self):
        for label, words in (
            ("47A", ("Compound", "4", "7", "B")),
            ("47B", ("Compound", "4", "7", "D")),
            ("X-47", ("Compound", "I-", "4", "7")),
            ("47", ("Compound", "I-", "4", "7")),
        ):
            with self.subTest(label=label, words=words):
                self.assertTrue(
                    refined_caption_conflicts(
                        label,
                        complete(label),
                        [fragment(word, index) for index, word in enumerate(words)],
                    )
                )

    def test_weak_separator_does_not_hide_duplicate_qualified_digits(self):
        original = [
            fragment("Compound", 0),
            fragment("4", 1),
            fragment("noise", 2, confidence=0.2),
            fragment("4", 3),
        ]
        self.assertTrue(refined_caption_conflicts("47", complete("47"), original))

    def test_zero_typography_is_literal_not_numeric_equivalence(self):
        for label, words in (
            ("47", ("Compound", "0", "4", "7")),
            ("047", ("Compound", "0", "0", "4", "7")),
            ("47", ("Compound", "4", "7", "²")),
        ):
            with self.subTest(label=label, words=words):
                self.assertTrue(
                    refined_caption_conflicts(
                        label,
                        complete(label),
                        [fragment(word, index) for index, word in enumerate(words)],
                    )
                )

    def test_whole_claims_and_nonfinal_roles_are_still_vetoes(self):
        for words in (("Compound 4", "7"), ("Intermediate", "4", "7")):
            with self.subTest(words=words):
                self.assertTrue(
                    refined_caption_conflicts(
                        "47",
                        complete("47"),
                        [fragment(word, index) for index, word in enumerate(words)],
                    )
                )

    def test_same_guard_replays_serialized_observations_at_existing_confidence_floor(
        self,
    ):
        for confidence, conflict in ((0.84, False), (0.85, True)):
            packet = json.loads(
                json.dumps(
                    {
                        "parts": complete("47A"),
                        "detection_parts": [
                            fragment("Compound", 0),
                            fragment("4", 1),
                            fragment("7", 2),
                            fragment("B", 3, confidence),
                        ],
                    }
                )
            )
            with self.subTest(confidence=confidence):
                self.assertEqual(
                    refined_caption_conflicts(
                        "47A",
                        packet["parts"],
                        packet["detection_parts"],
                    ),
                    conflict,
                )

    def test_complete_observation_must_match_claimed_identifier(self):
        self.assertTrue(
            refined_caption_conflicts(
                "47",
                complete("48"),
                [fragment("Compound", 0), fragment("4", 1), fragment("7", 2)],
            )
        )

    def test_removing_refinement_marker_cannot_erase_retained_literal_conflict(self):
        parts = complete("47A")
        del parts[0]["method"]
        self.assertTrue(
            refined_caption_conflicts(
                "47A",
                parts,
                [
                    fragment("Compound", 0),
                    fragment("4", 1),
                    fragment("7", 2),
                    fragment("B", 3),
                ],
            )
        )

    def test_detected_whole_caption_cannot_drop_the_original_detector_packet(self):
        parts = complete("47A")
        del parts[0]["method"]
        self.assertTrue(refined_caption_conflicts("47A", parts, None))

    def test_partial_prefixed_detection_needs_exact_qualified_boundary_overlap(self):
        partial, full = fragment("Compound 4", 0), fragment("47", 1)
        partial["bbox"] = [[8, 8], [85, 8], [85, 42], [8, 42]]
        self.assertFalse(
            refined_caption_conflicts("47", complete("47"), [partial, full])
        )
        for text, score, box in (
            ("48", 0.99, full["bbox"]),
            ("47", 0.2, full["bbox"]),
            ("47", 0.99, [[100, 8], [130, 8], [130, 42], [100, 42]]),
            ("47", 0.99, [[20, 8], [60, 8], [60, 42], [20, 42]]),
            ("47", 0.99, [[63, 50], [108, 50], [108, 80], [63, 80]]),
        ):
            with self.subTest(text=text, score=score, box=box):
                original = [
                    partial,
                    {**full, "text": text, "confidence": score, "bbox": box},
                ]
                self.assertTrue(
                    refined_caption_conflicts("47", complete("47"), original)
                )

    def test_scalar_number_observations_do_not_acquire_caption_detector_requirements(
        self,
    ):
        scalar = [{"text": "Compound 47", "confidence": 0.99, "bbox": None}]
        self.assertFalse(refined_caption_conflicts("47", scalar, []))


if __name__ == "__main__":
    unittest.main()
