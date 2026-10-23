"""Literal paragraph locators cannot mix table identity or assay conditions."""

import unittest

from patent_sar_extractor.core.activity_continuation_policy import (
    caption_prefix,
    continued_context_prefix,
)
from patent_sar_extractor.core.activity_headers import (
    context_from_text,
    context_source_text,
    grid_schema,
)
from patent_sar_extractor.core.activity_source_discovery import declared_activity_source
from patent_sar_extractor.core.biology_tables import biology_grid_schema
from patent_sar_extractor.core.source_result_references import (
    result_reference_sentences,
)
from patent_sar_extractor.core.source_section_roles import section_heading
from patent_sar_extractor.core.source_table_markers import caption_table_marker

PREFIXES = ("[0042] ", "[42] ", "[ 42 ] ", "［００４２］ ", "［ ４２ ］ ")
TITLE = "Table 9. Cellular activity"


class SourceCaptionLocatorTests(unittest.TestCase):
    def test_new_caption_does_not_borrow_an_earlier_target_or_assay(self):
        previous = "Table 8. Target: ABL; Assay: binding\nDuration: 2 h\n"
        for prefix in PREFIXES:
            current = prefix + TITLE + "\nCell line: U2OS\nDuration: 24 h"
            source = previous + current
            with self.subTest(prefix=prefix):
                context = context_from_text(source, source)
                self.assertEqual(context.table_id, "Table 9")
                self.assertEqual(context.caption, TITLE)
                self.assertIsNone(context.target)
                self.assertIsNone(context.assay)
                self.assertEqual(context.cell_line, "U2OS")
                self.assertEqual(context.duration, "24 h")
                self.assertEqual(context.raw_caption, prefix + TITLE)
                self.assertEqual(context.raw_context, source)
                self.assertEqual(context_source_text(source), current)
                schema = grid_schema(context, [["No.", "IC50 (nM)"], ["17B", "2.3"]])
                self.assertIsNotNone(schema)
                self.assertEqual(schema.context, context)
                self.assertEqual(schema.raw_headers, ("No.", "IC50 (nM)"))

    def test_nomination_and_molecular_headings_share_bounded_literal_locators(self):
        for prefix in PREFIXES:
            with self.subTest(prefix=prefix):
                marker = caption_table_marker(prefix + TITLE)
                self.assertIsNotNone(marker)
                self.assertEqual(marker.group(), "Table 9")
                heading = section_heading(prefix + "Compound 17B: Preparation")
                self.assertEqual(heading["identifier"], "17B")
                self.assertEqual(
                    heading["line_text"], prefix + "Compound 17B: Preparation"
                )

    def test_paragraph_label_alone_does_not_become_a_caption(self):
        for prefix in PREFIXES:
            raw = prefix.strip()
            with self.subTest(prefix=prefix):
                context = context_from_text(raw, raw)
                self.assertEqual(context.caption, "")
                self.assertEqual(context.raw_caption, "")
                self.assertEqual(context.raw_context, raw)
                self.assertIsNone(context.target)
                self.assertIsNone(context.assay)

    def test_paragraph_only_line_is_body_not_a_missing_table_title(self):
        for prefix in PREFIXES:
            body = prefix.strip() + "\nTarget: MET"
            source = "Table 9.\n" + body
            with self.subTest(prefix=prefix):
                context = context_from_text(source, source)
                self.assertEqual(context.caption, "Table 9.")
                self.assertEqual(context.raw_caption, "Table 9.")
                self.assertEqual(context.body_text, body)
                self.assertEqual(context.target, "MET")

    def test_changed_paragraph_locator_does_not_break_an_explicit_continued_table(self):
        original = "[0041] " + TITLE + "\nTarget: ABL\nDuration: 24 h"
        context = context_from_text(original, original)
        for prefix in PREFIXES:
            title = prefix + TITLE + " (continued)"
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    caption_prefix(
                        title, context.table_id, context.raw_caption, continued=True
                    )
                )
                self.assertTrue(
                    continued_context_prefix(title + "\nDuration: 24 h", context)
                )
                self.assertFalse(
                    continued_context_prefix(title + "\nDuration: 48 h", context)
                )
                self.assertFalse(
                    continued_context_prefix(title + "\nCell line: U2OS", context)
                )
                self.assertFalse(
                    continued_context_prefix(
                        title.replace("Table 9", "Table 10"), context
                    )
                )
                self.assertEqual(context.raw_caption, "[0041] " + TITLE)

    def test_malformed_locators_and_body_references_do_not_nominate_captions(self):
        for prefix in ("[0042 ", "［0042] ", "[0042］ ", "[123456789] ", "42 ", "See "):
            raw = prefix + TITLE
            with self.subTest(prefix=prefix):
                self.assertIsNone(caption_table_marker(raw))
                self.assertFalse(caption_prefix(raw, "Table 9", TITLE))
                self.assertIsNone(section_heading(prefix + "Compound 17B: Preparation"))

    def test_prose_reference_does_not_replace_the_last_literal_caption(self):
        for prefix in PREFIXES:
            source = prefix + TITLE + "\nTarget: MET\nThe results refer to Table 8."
            with self.subTest(prefix=prefix):
                context = context_from_text(source, source)
                self.assertEqual(context.table_id, "Table 9")
                self.assertEqual(context.target, "MET")
                self.assertEqual(context.raw_context, source)

    def test_source_discovery_and_result_references_keep_the_same_literal_windows(self):
        for prefix in PREFIXES:
            raw = prefix + "The results are shown in Tables 9 and 10."
            with self.subTest(prefix=prefix):
                references = result_reference_sentences(raw)
                self.assertEqual(len(references), 1)
                self.assertEqual(references[0].targets, ("Table 9", "Table 10"))
                self.assertEqual(references[0].raw_text, raw)
                self.assertTrue(declared_activity_source(prefix + TITLE))

    def test_readout_method_does_not_fill_an_undeclared_experimental_context(self):
        for title, headers in (
            ("HTRF binding activity", ["No.", "HTRF Ratio", "Grade"]),
            ("Anti-proliferation activity", ["No.", "Anti-proliferation"]),
        ):
            raw = "Table 9. " + title
            context = context_from_text(raw, raw)
            with self.subTest(title=title):
                schema = biology_grid_schema(grid_schema(context, [headers]))
                self.assertEqual(schema.semantic_kind, "biology")
                self.assertEqual(schema.context, context)
                self.assertIsNone(schema.context.assay)
                self.assertIsNone(schema.context.target)
                self.assertEqual(schema.context.raw_caption, raw)

    def test_declared_context_and_conflicting_literal_target_are_not_silenced(self):
        raw = "Table 9. CRBN binding measured by HTRF\nTarget: EGFR; Assay: enzyme"
        context = context_from_text(raw, raw)
        schema = biology_grid_schema(
            grid_schema(context, [["No.", "HTRF Ratio", "Grade"]])
        )
        self.assertEqual(schema.context, context)
        self.assertEqual(schema.context.target, "EGFR")
        self.assertEqual(schema.context.assay, "enzyme")
        self.assertTrue(schema.needs_review)


if __name__ == "__main__":
    unittest.main()
