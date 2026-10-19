"""Literal declarations, not narrative captions, own experimental conditions."""

import unittest

from patent_sar_extractor.core.activity_header_identity import (
    context_conflict,
    schema_requires_review,
)
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.biology_tables import biology_grid_schema, infer_schema
from patent_sar_extractor.web.artifacts import _activities


class ExplicitActivityContextTests(unittest.TestCase):
    def test_narrative_spelling_is_preserved_but_is_not_an_assay_identity(self):
        old = "Table 7. Comparison of compound activity in a functional assay"
        fresh = "Table 7. Comparison of conpound activity in a functional assay"
        before, after = context_from_text(old), context_from_text(fresh)
        self.assertIsNone(before.assay)
        self.assertIsNone(after.assay)
        self.assertEqual(before.raw_caption, old)
        self.assertEqual(after.raw_context, fresh)
        self.assertFalse(context_conflict(before, after))

    def test_explicit_fields_are_complete_and_do_not_swallow_following_labels(self):
        raw = (
            "Table 7. Activities\nTarget: Human kinase domain; Assay: HTRF binding; "
            "Cell line: HEK293; Construct: WT 1-300; Duration: 24 h; "
            "Treatment duration: 24 h; Timepoint: 48 h; Batch: B1"
        )
        context = context_from_text(raw)
        for key, value in {
            "target": "Human kinase domain",
            "assay": "HTRF binding",
            "cell_line": "HEK293",
            "construct": "WT 1-300",
            "duration": "24 h",
            "treatment_duration": "24 h",
            "timepoint": "48 h",
            "batch": "B1",
        }.items():
            self.assertEqual(getattr(context, key), value, key)
        self.assertEqual(context.raw_context, raw)

    def test_adjacent_labels_and_chinese_declarations_keep_their_literal_values(self):
        context = context_from_text(
            "Table 4\n靶点：靶蛋白甲；实验：结合实验；细胞系：细胞乙；"
            "构建体：野生型；处理时长：24小时；时间点：48小时；批次：甲"
        )
        self.assertEqual(context.target, "靶蛋白甲")
        self.assertEqual(context.assay, "结合实验")
        self.assertEqual(context.duration, "24小时")
        adjacent = context_from_text(
            "Table 4\nTarget: T Assay: binding Cell line: C1 Duration: 24 h"
        )
        self.assertEqual(adjacent.assay, "binding")
        self.assertEqual(adjacent.target, "T")
        self.assertEqual(adjacent.duration, "24 h")

    def test_valid_conflicting_claims_do_not_pick_a_first_or_last_winner(self):
        for field, first, second in (
            ("Assay", "binding", "degradation"),
            ("Target", "A", "B"),
            ("Duration", "24 h", "48 h"),
            ("Cell line", "HEK293", "A549"),
        ):
            raw = f"Table 8\n{field}: {first}; {field}: {second}"
            context = context_from_text(raw)
            self.assertTrue(context.claim_conflicts)
            schema = grid_schema(context, [["No.", "IC50 (nM)"]])
            self.assertTrue(schema_requires_review(schema))
            self.assertTrue(context_conflict(context, context))
            self.assertEqual(context.raw_context, raw)

    def test_known_conditions_cannot_be_overruled_by_a_different_complete_read(self):
        for before, after in (
            ("Assay: binding", "Assay: degradation"),
            ("Duration: 24 h", "Duration: 48 h"),
            ("Construct: WT", "Construct: mutant"),
            ("Batch: B1", "Batch: B2"),
        ):
            self.assertTrue(
                context_conflict(
                    context_from_text("Table 7\n" + before),
                    context_from_text("Table 7\n" + after),
                )
            )

    def test_last_owned_caption_cannot_inherit_or_conflict_with_a_previous_table(self):
        context = context_from_text(
            "",
            "Table 1\nAssay: alpha; Duration: 6 h\n"
            "Table 2\nAssay: beta; Duration: 24 h",
        )
        self.assertEqual(context.table_id, "Table 2")
        self.assertEqual(context.assay, "beta")
        self.assertEqual(context.duration, "24 h")
        self.assertFalse(context.claim_conflicts)
        self.assertIn("Assay: alpha", context.raw_context)

    def test_repeated_identical_declarations_are_not_conflicts_or_extra_measurements(
        self,
    ):
        context = context_from_text(
            "Table 9\nAssay: binding; Assay: binding; Duration: 24 h; Duration: 24 h"
        )
        self.assertEqual(context.assay, "binding")
        self.assertFalse(context.claim_conflicts)

    def test_explicit_next_line_value_remains_owned_and_partial_missing_is_not_a_vote(
        self,
    ):
        complete = context_from_text("Table 9\nAssay:\nHTRF binding\nTarget: T")
        self.assertEqual(complete.assay, "HTRF binding")
        self.assertFalse(complete.claim_conflicts)
        fragment = context_from_text("", "Assay:")
        self.assertTrue(context_conflict(fragment, complete))
        self.assertFalse(context_conflict(fragment, complete, partial=True))
        known = context_from_text("", "Assay: degradation")
        self.assertTrue(context_conflict(known, complete, partial=True))
        partial = context_from_text("", "Assay: HTRF", partial=True)
        self.assertFalse(context_conflict(partial, complete, partial=True))
        self.assertTrue(context_conflict(partial, complete))
        mixed = context_from_text("", "Assay: degradation; Assay:", partial=True)
        self.assertTrue(context_conflict(mixed, complete, partial=True))

    def test_undeclared_optional_conditions_are_not_added_as_unknown_scientific_fields(
        self,
    ):
        context = context_from_text(
            "Table 1\nTarget: T; Assay: binding; Cell line: C1; Duration: 24 h"
        )
        self.assertEqual(
            context.scientific_values(),
            {"target": "T", "assay": "binding", "cell_line": "C1", "duration": "24 h"},
        )

    def test_conflicting_duration_aliases_stay_raw_and_unresolved(self):
        context = context_from_text("Table 7\nDuration: 24 h; Treatment duration: 48 h")
        self.assertTrue(context.claim_conflicts)
        self.assertEqual(context.duration, "24 h")
        self.assertEqual(context.treatment_duration, "48 h")

    def test_unlabelled_cell_names_do_not_pick_generic_words_or_a_last_winner(self):
        source = context_from_text(
            "Table 7\nHEK293 cells were incubated. All cells were measured."
        )
        self.assertEqual(source.cell_line, "HEK293")
        self.assertIsNone(
            context_from_text("Table 7\nThe cells were cultured.").cell_line
        )
        for name in ("Jurkat", "HeLa", "THP-1"):
            self.assertEqual(
                context_from_text(f"Table 7\n{name} cells").cell_line, name
            )
        mixed = context_from_text("Table 7\nHEK293 cells and A549 cells")
        self.assertIsNone(mixed.cell_line)
        self.assertTrue(mixed.claim_conflicts)
        bio = infer_schema(
            "Table 7. Ranking of T degradation in HEK293 cells and A549 cells", 2
        )
        self.assertIsNone(bio.cell_line)
        self.assertTrue(bio.context_conflicts)

    def test_named_assay_is_not_replaced_or_compared_to_a_biological_method_name(self):
        context = context_from_text("Table 7. HTRF Ratio\nAssay name: Alpha binding")
        schema = biology_grid_schema(grid_schema(context, [["No.", "Ratio", "Grade"]]))
        self.assertEqual(schema.semantic_kind, "biology")
        self.assertEqual(schema.context.assay, "Alpha binding")
        self.assertFalse(schema.needs_review)

    def test_overlong_or_incomplete_declarations_never_publish_a_truncated_identity(
        self,
    ):
        for declaration in ("Assay:", "Assay: " + "x" * 1001, "Assay: binding; " * 33):
            context = context_from_text("Table 9\n" + declaration)
            self.assertTrue(context.claim_conflicts)
            self.assertTrue(
                schema_requires_review(grid_schema(context, [["No.", "IC50 (nM)"]]))
            )

    def test_unknown_assays_from_independent_tables_stay_in_separate_read_namespaces(
        self,
    ):
        scopes = []
        for table, box in (
            ("Table 4", [10, 20, 200, 40]),
            ("Table 5", [10, 200, 200, 220]),
        ):
            values = _activities(
                {
                    "activity_values": {"IC50 (nM)": "1"},
                    "activity_sources": [
                        {
                            "page_no": 1,
                            "table_id": table,
                            "assay": None,
                            "header_region": {"page_no": 1, "bbox": box},
                            "cells": [{"field": "IC50 (nM)", "value": "1"}],
                        }
                    ],
                },
                page_count=1,
            )
            self.assertIsNone(values[0].assay)
            scopes.append(values[0].source_scope)
        self.assertNotEqual(*scopes)
