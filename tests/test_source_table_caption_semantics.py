"""Pure original-caption grammar, independent of PDF/OCR environments."""

import unittest

from patent_sar_extractor.core.caption_role_semantics import (
    catalog_title_role,
    continuation_title,
    has_continuation_caption,
)
from patent_sar_extractor.core.source_table_markers import (
    TABLE_MARKER,
    caption_table_marker,
    table_marker_identity,
)


class SourceTableCaptionSemanticsTests(unittest.TestCase):
    def test_source_table_roles_allow_only_a_real_caption_prefix(self):
        self.assertEqual(
            catalog_title_role("[0042] Table 12. Intermediate compounds"), "nonfinal"
        )
        self.assertEqual(
            catalog_title_role("Table ABC. Intermediate compounds"), "nonfinal"
        )
        self.assertFalse(continuation_title("Results continued in Table 12."))
        self.assertTrue(continuation_title("[0042] Table 12. Continued"))

    def test_continuation_words_respect_literal_punctuation_not_substrings(self):
        for text in (
            "Table A (cont.)",
            "Table 9. Cont.",
            "Table 9 Continued",
            "表B 续表",
        ):
            self.assertTrue(continuation_title(text), text)
        for text in (
            "Table A. Content",
            "Table 9 discontinued",
            "Table 9 cont.measurement",
            "Continued experiment",
        ):
            self.assertFalse(continuation_title(text), text)

    def test_literal_table_identity_does_not_match_prose_or_invent_a_key(self):
        for text, expected in (
            ("Table A. Results", "Table A"),
            ("Tabie B. Continued", "Table B"),
            ("TableB12. Compounds", "Table B12"),
            ("Table A-12. Compounds", "Table A-12"),
            ("Table 3-2. Results", "Table 3-2"),
            ("表 A：结果", "表 A"),
            ("表B：续表", "表B"),
            ("表B80：结果", "表B80"),
        ):
            with self.subTest(text=text):
                marker = TABLE_MARKER.search(text)
                self.assertIsNotNone(marker)
                self.assertEqual(table_marker_identity(marker.group()), expected)
        for text in ("Tablet formulation", "Table affinity", "TableColumns", "表格"):
            self.assertIsNone(TABLE_MARKER.search(text))
        self.assertIsNone(caption_table_marker("According to Table 12. Compounds"))
        self.assertIsNone(caption_table_marker("Table ABC. Intermediate compounds"))

    def test_page_hints_require_a_real_caption_on_one_original_line(self):
        self.assertTrue(
            has_continuation_caption("Other source text\n[0042] Table A. Continued\n73")
        )
        self.assertFalse(
            has_continuation_caption("The results continued in Table A.\n73")
        )

    def test_adjacent_letter_digit_table_names_keep_the_same_caption_identity(self):
        self.assertTrue(continuation_title("[0042] TableB12. Continued"))
        self.assertTrue(continuation_title("TableA-12. Cont."))
        self.assertFalse(continuation_title("Tablet. Continued"))

    def test_a_mixed_category_cannot_be_excluded_as_intermediate_only(self):
        self.assertEqual(
            catalog_title_role("[0042] Table 12. Compounds and intermediates"), "mixed"
        )
        self.assertEqual(
            catalog_title_role("See Table 12. Intermediate compounds"), "unknown"
        )
