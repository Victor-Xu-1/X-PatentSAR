"""Unproved literal table boundaries cannot borrow an earlier scientific context."""

import unittest
from contextlib import nullcontext
from dataclasses import asdict
from unittest.mock import patch

from patent_sar_extractor.core import page_ocr_cache
from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_continuation_policy import (
    continued_context_prefix,
)
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_header_identity import schema_requires_review
from patent_sar_extractor.core.activity_headers import (
    context_from_text,
    context_source_text,
    grid_schema,
)
from patent_sar_extractor.core.activity_models import TableContext
from patent_sar_extractor.core.activity_source_discovery import declared_activity_source
from patent_sar_extractor.core.source_section_roles import (
    procedure_heading_boundary,
    section_heading,
)
from patent_sar_extractor.core.source_table_markers import caption_table_marker
from patent_sar_extractor.web.artifacts import _activities
from tests.test_caption_locator_native import caption_document

MALFORMED = (
    "[0042",
    "［0042]",
    "[0042］",
    "[123456789]",
    "［ ４２",
    "[" + "1" * 129 + "]",
)
OLD = "Table 8. Target: ABL; Assay: binding\nDuration: 2 h\n"
TITLE = "Table 9. Cellular activity"


class UnprovedCaptionBoundaryTests(unittest.TestCase):
    def test_unproved_new_title_withholds_old_fields_and_keeps_its_original_window(
        self,
    ):
        for prefix in MALFORMED:
            current = prefix + " " + TITLE + "\nCell line: U2OS\nDuration: 24 h"
            raw = OLD + current
            with self.subTest(prefix=prefix[:20]):
                context = context_from_text(raw, raw)
                self.assertIsNone(context.target)
                self.assertIsNone(context.assay)
                self.assertEqual(context.table_id, "")
                self.assertEqual(context.cell_line, "U2OS")
                self.assertEqual(context.duration, "24 h")
                self.assertEqual(context.raw_context, raw)
                self.assertEqual(context.raw_caption, prefix + " " + TITLE)
                self.assertEqual(context_source_text(raw), current)
                self.assertIn(
                    "table_id:unproved_caption_prefix", context.claim_conflicts
                )
                self.assertTrue(
                    schema_requires_review(grid_schema(context, [["No.", "IC50 (nM)"]]))
                )

    def test_source_nomination_retains_unproved_activity_without_certifying_a_title(
        self,
    ):
        for prefix in MALFORMED:
            raw = prefix + " " + TITLE
            with self.subTest(prefix=prefix[:20]):
                self.assertTrue(
                    declared_activity_source("Table 8. NMR characterization\n" + raw)
                )
                self.assertIsNone(caption_table_marker(raw))
                self.assertIsNone(section_heading(raw))
                self.assertTrue(procedure_heading_boundary(raw))

    def test_prose_and_isotope_labels_do_not_become_numeric_paragraph_boundaries(self):
        for line in (
            "The results refer to Table 9.",
            "See Table 9.",
            "[13C] labels are listed in Table 9.",
            "[see] Table 9.",
            "[0042] The results refer to Table 9.",
        ):
            with self.subTest(line=line):
                context = context_from_text(OLD + line, OLD + line)
                self.assertEqual(context.table_id, "Table 8")
                self.assertEqual(context.target, "ABL")
                self.assertEqual(context.assay, "binding")
                self.assertNotIn(
                    "table_id:unproved_caption_prefix", context.claim_conflicts
                )
                self.assertIsNone(caption_table_marker(line))

    def test_native_original_cannot_publish_a_new_grids_rows_in_the_previous_assay(
        self,
    ):
        with (
            patch.object(page_ocr_cache, "_OCR_ENGINE", None),
            patch.object(
                page_ocr_cache,
                "_build_ocr_engine",
                side_effect=AssertionError("No native OCR"),
            ) as engine,
            caption_document(current_prefix="[0042") as document,
        ):
            parsed = extract_coordinate_tables(document, [0])
            self.assertEqual([row.cpd for row in parsed.rows], ["Compound 17B"])
            row = parsed.rows[0]
            self.assertTrue(row.needs_review)
            self.assertEqual(row.activity_values, {"IC50 (nM)": "2.3"})
            source = row.activity_sources[0]
            self.assertIsNone(source["target"])
            self.assertIsNone(source["assay"])
            self.assertEqual(source["raw_caption"], "[0042 " + TITLE)
            projected = _activities(asdict(row), page_count=1)
            self.assertEqual(len(projected), 1)
            self.assertIsNone(projected[0].target)
            self.assertIsNone(projected[0].assay)
            self.assertNotEqual(projected[0].source_table, "Table 8")
            payload = {"coverage": {"regions": parsed.coverage}, "rows": [asdict(row)]}
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                )
            )
            engine.assert_not_called()

    def test_saved_raw_context_cannot_erase_the_unproved_boundary_by_omitting_a_caption(
        self,
    ):
        context = TableContext(
            table_id="Table 9", target="ABL", raw_context=OLD + "[0042 " + TITLE
        )
        self.assertIn("table_id:unproved_caption_prefix", context.claim_conflicts)
        self.assertTrue(
            schema_requires_review(grid_schema(context, [["No.", "IC50 (nM)"]]))
        )

    def test_a_later_literal_title_owns_only_its_own_conditions(self):
        raw = OLD + "[0042 " + TITLE + "\n[0043] Table 10. Activity\nTarget: MET"
        context = context_from_text(raw, raw)
        self.assertEqual(context.table_id, "Table 10")
        self.assertEqual(context.target, "MET")
        self.assertIsNone(context.assay)
        self.assertEqual(context.claim_conflicts, ())
        self.assertEqual(context.raw_context, raw)

    def test_broken_prefix_never_grants_continuation_even_with_matching_known_fields(
        self,
    ):
        context = context_from_text("[0042 " + TITLE + "\nTarget: MET")
        self.assertFalse(
            continued_context_prefix(
                "Table 9. Cellular activity (continued)\nTarget: MET", context
            )
        )
        valid = context_from_text("[ 42\n] " + TITLE + "\nTarget: MET")
        self.assertEqual(valid.table_id, "Table 9")
        self.assertEqual(valid.target, "MET")
        self.assertEqual(valid.claim_conflicts, ())


if __name__ == "__main__":
    unittest.main()
