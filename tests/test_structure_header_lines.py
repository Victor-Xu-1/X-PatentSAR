"""Renderer-free original-line geometry and complete-word preservation."""

import copy
import unittest

from patent_sar_extractor.core.structure_header_lines import original_header_groups


def word(text, left, top, right):
    return {
        "text": text,
        "bbox": [left, top, right, top + 10],
        "x": (left + right) / 2,
        "y": top + 5,
    }


class StructureHeaderLineTests(unittest.TestCase):
    def setUp(self):
        self.bounds = [0, 0, 520, 720]
        self.tokens = [
            word("Compound", 50, 70, 108),
            word("Chemical", 240, 70, 290),
            word("No.", 50, 84, 68),
            word("Structure", 240, 84, 290),
        ]

    def test_full_original_multiline_words_replace_only_a_contained_partial_nomination(
        self,
    ):
        groups = original_header_groups(self.tokens, self.bounds)
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            [g["text"] for g in groups[0]], ["Compound\nNo.", "Chemical\nStructure"]
        )
        self.assertEqual(
            [g["bbox"] for g in groups[0]], [[50, 70, 108, 94], [240, 70, 290, 94]]
        )

    def test_an_original_column_can_start_on_the_second_printed_line(self):
        tokens = [
            word("Chemical", 240, 70, 290),
            word("Compound No.", 50, 84, 115),
            word("Structure", 240, 84, 290),
        ]
        groups = original_header_groups(tokens, self.bounds)
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            [g["text"] for g in groups[0]], ["Compound No.", "Chemical\nStructure"]
        )

    def test_unknown_prefix_cannot_be_deleted_to_turn_its_suffix_into_a_structure_role(
        self,
    ):
        tokens = [
            word("Not a", 240, 70, 290),
            word("Compound No.", 50, 84, 115),
            word("Structure", 240, 84, 290),
        ]
        self.assertEqual(original_header_groups(tokens, self.bounds), [])

    def test_a_close_first_original_identifier_row_is_not_appended_to_the_header(self):
        tokens = self.tokens + [word("73", 50, 98, 65)]
        groups = original_header_groups(tokens, self.bounds)
        self.assertEqual(groups[0][-1]["bbox"][3], 94)
        self.assertNotIn("73", " ".join(g["text"] for g in groups[0]))

    def test_a_later_original_caption_stops_header_word_carry(self):
        tokens = self.tokens + [
            word("Table 13. Compounds", 40, 98, 150),
            word("Compound No.", 50, 130, 115),
            word("Structure", 240, 130, 290),
        ]
        groups = original_header_groups(tokens, self.bounds)
        self.assertEqual(len(groups), 2)
        self.assertEqual([g["text"] for g in groups[1]], ["Compound No.", "Structure"])

    def test_original_word_order_is_geometric_and_input_tokens_are_not_rewritten(self):
        before = copy.deepcopy(self.tokens)
        self.assertEqual(
            original_header_groups(list(reversed(self.tokens)), self.bounds),
            original_header_groups(self.tokens, self.bounds),
        )
        self.assertEqual(self.tokens, before)

    def test_overlong_connected_header_is_explicit_not_a_truncated_success(self):
        tokens = [word("Compound", 50, 40, 108), word("Structure", 240, 40, 290)]
        tokens += [word("word", 50, 54 + i * 14, 80) for i in range(8)]
        with self.assertRaises(ValueError):
            original_header_groups(tokens, self.bounds)


if __name__ == "__main__":
    unittest.main()
