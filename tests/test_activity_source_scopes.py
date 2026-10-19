"""Independent original experiments survive presentation and SAR preparation."""

import copy
import unittest

from pydantic import ValidationError

from patent_sar_extractor.web.activity_columns import ActivityColumnCatalog
from patent_sar_extractor.web.activity_focus import matching_cells
from patent_sar_extractor.web.activity_provenance import source_evidence
from patent_sar_extractor.web.activity_scope import validate_scope_edits
from patent_sar_extractor.web.artifacts import _activities
from patent_sar_extractor.web.errors import WebError


def source_row(table=1, *, value="1", page=1, header_page=1, cell_line="HEK293"):
    top = 20 + (table - 1) * 150
    return {
        "cpd": "1",
        "page_no": page,
        "activity_values": {"IC50 (nM)": value},
        "activity_sources": [
            {
                "page_no": page,
                "table_id": f"Table {table}",
                "target": "TargetA",
                "assay": "Binding",
                "cell_line": cell_line,
                "duration": "24 h",
                "geometry_space": "rendered",
                "table_bbox": [20, top, 200, top + 100],
                "header_region": {
                    "page_no": header_page,
                    "bbox": [20, top, 200, top + 20],
                },
                "cells": [
                    {"field": "compound_id", "value": "1"},
                    {"field": "IC50 (nM)", "value": value},
                ],
            }
        ],
    }


class ActivitySourceScopeTests(unittest.TestCase):
    def test_same_value_and_labels_in_two_original_tables_are_not_one_observation(self):
        row = source_row()
        row["activity_sources"].extend(source_row(2)["activity_sources"])
        before = copy.deepcopy(row)
        activities = _activities(row, page_count=5)
        self.assertEqual(len(activities), 2)
        self.assertEqual(row, before)
        self.assertNotEqual(activities[0].source_scope, activities[1].source_scope)

    def test_tenth_strongest_scales_do_not_pool_independent_tables(self):
        catalog = ActivityColumnCatalog()
        for table, multiplier in ((1, 1), (2, 1000)):
            for number in range(1, 11):
                values = _activities(
                    source_row(table, value=str(number * multiplier)), page_count=5
                )
                catalog.observe(values, compound_id=str(number))
        columns = catalog.columns()
        self.assertEqual(len(columns), 2)
        self.assertEqual(
            {c.strength_scale.anchor_lower for c in columns}, {10.0, 10000.0}
        )

    def test_header_continuation_preserves_scope_but_cell_conditions_do_not_merge(self):
        first = _activities(source_row(), page_count=5)[0]
        continuation = _activities(source_row(page=2), page_count=5)[0]
        other_cells = _activities(source_row(cell_line="A549"), page_count=5)[0]
        self.assertEqual(first.source_scope, continuation.source_scope)
        self.assertNotEqual(first.source_scope, other_cells.source_scope)

    def test_values_and_body_pages_do_not_change_an_original_context_origin(self):
        a = _activities(source_row(), page_count=5)[0]
        b = _activities(source_row(value="100", page=3), page_count=5)[0]
        self.assertEqual(a.source_scope, b.source_scope)
        self.assertEqual(b.source_context_page, 1)

    def test_identical_table_geometry_in_other_original_documents_is_not_the_same_scope(
        self,
    ):
        a = _activities(source_row(), page_count=5, document_sha256="a" * 64)[0]
        b = _activities(source_row(), page_count=5, document_sha256="b" * 64)[0]
        self.assertNotEqual(a.source_scope, b.source_scope)
        with self.assertRaises(WebError):
            _activities(source_row(), page_count=5, document_sha256="invalid")

    def test_missing_legacy_anchor_is_not_invented_from_table_name(self):
        row = source_row()
        del row["activity_sources"][0]["header_region"]
        item = _activities(row, page_count=5)[0]
        self.assertIsNone(item.source_scope)
        self.assertNotIn("source_scope", item.model_dump())

    def test_text_continuations_share_the_recorded_original_span(self):
        row = source_row()
        source = row["activity_sources"][0]
        del source["header_region"]
        source["text_scope"] = {"span": [10, 20], "origin": [1, 10, 20], "parent": None}
        first = _activities(row, page_count=5)[0]
        source["page_no"] = 2
        source["text_scope"].update(span=[30, 40], parent=[1, 10, 20])
        self.assertEqual(
            first.source_scope, _activities(row, page_count=5)[0].source_scope
        )

    def test_malformed_present_origins_fail_without_a_legacy_fallback(self):
        for change in (
            {"page_no": True, "bbox": [0, 1, 2, 3]},
            {"page_no": 2, "bbox": [0, 1, 2, 3]},
            {"page_no": 1, "bbox": [0, 3, 2, 1]},
            {"page_no": 1, "bbox": [0, 1, float("nan"), 3]},
        ):
            row = source_row()
            row["activity_sources"][0]["header_region"] = change
            with self.subTest(change=change), self.assertRaises(WebError):
                _activities(row, page_count=5)

    def test_numeric_edits_keep_scope_but_cannot_forge_a_table_or_target(self):
        original = _activities(source_row(), page_count=5)[0]
        validate_scope_edits([original.model_copy(update={"value": "2"})], [original])
        for field, value in (
            ("source_scope", "b" * 64),
            ("source_table", "Table 2"),
            ("source_context_page", 2),
            ("target", "OtherTarget"),
            ("source_conditions", {"cell_line": "A549"}),
        ):
            with self.subTest(field=field), self.assertRaises(WebError):
                validate_scope_edits(
                    [original.model_copy(update={field: value})], [original]
                )
        raw = original.model_dump()
        del raw["source_context_page"]
        with self.assertRaises(ValidationError):
            type(original).model_validate(raw)

    def test_scoped_numeric_edit_cannot_strip_its_original_namespace(self):
        original = _activities(source_row(), page_count=5)[0]
        stripped = original.model_copy(
            update={
                "source_scope": None,
                "source_table": None,
                "source_context_page": None,
                "source_conditions": {},
                "value": "2",
            }
        )
        with self.assertRaises(WebError) as caught:
            validate_scope_edits([stripped], [original])
        self.assertEqual(caught.exception.code, "correction_activity_origin")
        validate_scope_edits(
            [], [original]
        )  # Explicit removal remains an audited edit.

    def test_source_focus_does_not_highlight_a_different_identical_experiment(self):
        row = source_row()
        row["activity_sources"].extend(source_row(2)["activity_sources"])
        for index, source in enumerate(row["activity_sources"]):
            source["cells"][1]["bbox"] = [90, 60 + index * 150, 150, 80 + index * 150]
        activities = _activities(row, page_count=5)
        sources = source_evidence(row, (1, None, None), page_count=5)
        self.assertEqual(len(matching_cells(sources[0], "1", activities[0])), 1)
        self.assertEqual(matching_cells(sources[1], "1", activities[0]), [])
