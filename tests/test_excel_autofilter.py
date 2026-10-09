"""Excel selection semantics over real effective rows, not current-page DOM."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from patent_sar_extractor.web.activity_columns import ActivityColumnCatalog
from patent_sar_extractor.web.models import Activity, Compound, Confidence, Source
from patent_sar_extractor.web.table_filter_choices import filter_choices
from patent_sar_extractor.web.table_queries import workbook_rows
from patent_sar_extractor.web.table_query_models import ColumnFilter
from test_prediction_support import PredictionFixture, controlled_summary


def row(identifier, values):
    return Compound(
        id=identifier,
        display_id=identifier,
        activities=[Activity(name="IC50", value=value, unit="nM") for value in values],
        confidence=Confidence(level="unknown", score=None, reason="Controlled fixture"),
        source=Source(),
        flags=[],
    )


class AutoFilterLogicTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row("Compound 1", [1]),
            row("Compound 2", [2, 4]),
            row("Compound 10", [3]),
            row("Compound 11", []),
        ]
        catalog = ActivityColumnCatalog()
        for item in self.rows:
            catalog.observe(item.activities, compound_id=item.id)
        self.catalog = catalog.columns()
        self.column = "activity:" + self.catalog[0].id

    def select(self, **condition):
        criterion = ColumnFilter(column=self.column, **condition)
        return [
            item.id
            for item in workbook_rows(self.rows, [criterion], "", "asc", self.catalog)
        ]

    def test_checklist_includes_blank_without_losing_selected_values(self):
        self.assertEqual(
            self.select(op="in", values=["1"], include_empty=True),
            ["Compound 1", "Compound 11"],
        )
        self.assertEqual(self.select(op="in", values=[], include_empty=False), [])
        self.assertEqual(
            self.select(op="in", values=[], include_empty=True), ["Compound 11"]
        )

    def test_all_except_values_excludes_whole_multivalued_cell(self):
        self.assertEqual(
            self.select(op="not_in", values=["4"], include_empty=True),
            ["Compound 1", "Compound 10", "Compound 11"],
        )
        self.assertEqual(
            self.select(op="not_in", values=[], include_empty=False),
            ["Compound 1", "Compound 2", "Compound 10"],
        )

    def test_color_uses_complete_catalog_even_after_another_filter(self):
        conditions = [
            ColumnFilter(column="compound", op="ne", value="Compound 1"),
            ColumnFilter(column=self.column, op="band", value="strong"),
        ]
        result = workbook_rows(self.rows, conditions, "", "asc", self.catalog)
        self.assertEqual(result, [])
        self.assertEqual(
            self.select(op="band", value="none"), [item.id for item in self.rows]
        )

    def test_color_sort_and_natural_tie_sort(self):
        result = workbook_rows(self.rows, [], self.column, "asc", self.catalog, "none")
        self.assertEqual(
            [item.id for item in result],
            ["Compound 1", "Compound 2", "Compound 10", "Compound 11"],
        )

    def test_negative_text_conditions_and_prefix_suffix(self):
        for op, operand, expected in (
            ("starts_with", "1", ["Compound 1", "Compound 10", "Compound 11"]),
            ("ends_with", "1", ["Compound 1", "Compound 11"]),
            ("not_contains", "1", ["Compound 2"]),
        ):
            with self.subTest(op=op):
                items = workbook_rows(
                    self.rows,
                    [ColumnFilter(column="compound", op=op, value=operand)],
                    "",
                    "asc",
                )
                self.assertEqual([item.id for item in items], expected)

    def test_large_distinct_catalog_is_paged_and_naturally_ordered_not_truncated(self):
        rows = [row(f"Compound {index}", []) for index in range(1, 232)]
        first = filter_choices(rows, "compound", [], search="", page=1, page_size=200)
        second = filter_choices(rows, "compound", [], search="", page=2, page_size=200)
        self.assertEqual((first.total, second.total), (231, 231))
        self.assertEqual(first.items[0].value, "1")
        self.assertEqual(second.items[0].value, "201")
        self.assertEqual(len(second.items), 31)
        searched = filter_choices(
            rows, "compound", [], search="231", page=1, page_size=200
        )
        self.assertEqual([item.value for item in searched.items], ["231"])
        self.assertEqual(searched.matching_rows, 231)

    def test_choice_counts_are_per_row_and_blank_is_independent_of_search(self):
        rows = [row("one", [1, 1, None]), row("two", []), row("three", [2])]
        result = filter_choices(
            rows, self.column, self.catalog, search="1", page=1, page_size=200
        )
        self.assertEqual(
            [(item.value, item.count) for item in result.items], [("1", 1)]
        )
        self.assertEqual((result.empty_count, result.matching_rows), (1, 3))
        self.assertEqual(result.kind, "number")

    def test_presence_choices_do_not_disclose_image_urls(self):
        rows = [row("one", []), row("two", [])]
        rows[0].structure_image_url = "/api/v1/private-source-image"
        result = filter_choices(rows, "structure", [], search="", page=1, page_size=200)
        self.assertEqual(result.kind, "presence")
        self.assertEqual(result.items, [])
        self.assertEqual(result.empty_count, 1)

    def test_mixed_value_menu_uses_dominant_type_but_censored_values_stay_raw(self):
        rows = [row("one", [1]), row("two", [2]), row("three", ["<10"])]
        result = filter_choices(
            rows, self.column, self.catalog, search="<", page=1, page_size=200
        )
        self.assertEqual(result.kind, "number")
        self.assertEqual([item.value for item in result.items], ["<10"])
        filtered = workbook_rows(
            rows, [ColumnFilter(column=self.column, op="gt", value="1")], "", "asc"
        )
        self.assertEqual([item.id for item in filtered], ["two"])

    def test_checklist_distinguishes_actual_raw_values_without_case_folding(self):
        rows = [row("one", ["ND"]), row("two", ["nd"])]
        selected = workbook_rows(
            rows, [ColumnFilter(column=self.column, op="in", values=["ND"])], "", "asc"
        )
        self.assertEqual([item.id for item in selected], ["one"])


class AutoFilterAPITests(PredictionFixture, unittest.TestCase):
    def test_choices_keep_existing_session_and_origin_boundary(self):
        with self.client() as client:
            endpoint = f"/api/v1/projects/{self.project.id}/filter-values"
            response = client.get(
                endpoint,
                params={"column": "compound"},
                headers={"Origin": "http://untrusted.invalid"},
            )
            self.assertEqual(response.status_code, 403, response.text)
            client.cookies.clear()
            response = client.get(endpoint, params={"column": "compound"})
            self.assertEqual(response.status_code, 401, response.text)

    def test_choices_ignore_own_filter_and_honor_other_filters(self):
        with self.client() as client:
            base = f"/api/v1/projects/{self.project.id}"
            params = {
                "column": "compound",
                "column_filters": json.dumps(
                    [{"column": "compound", "op": "in", "values": []}]
                ),
            }
            response = client.get(base + "/filter-values", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                response.json()["items"], [{"value": "Compound 1", "count": 1}]
            )
            params["column_filters"] = json.dumps(
                [
                    {"column": "compound", "op": "in", "values": []},
                    {"column": "edit", "op": "eq", "value": "不存在"},
                ]
            )
            response = client.get(base + "/filter-values", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["matching_rows"], 0)

    def test_property_choices_use_stored_prediction_no_model_or_pdf(self):
        item = self.service.results(self.project.id).items[0]
        producer, _, source = self.draft()
        self.service.predictions.put(
            self.project.id,
            item.id,
            controlled_summary(source, item.smiles, producer["id"]),
        )
        with (
            self.client() as client,
            patch(
                "patent_sar_extractor.web.result_queries.open_pdf",
                side_effect=AssertionError("Choices must not open PDF"),
            ),
            patch(
                "patent_sar_extractor.web.prediction_jobs.enqueue_prediction",
                side_effect=AssertionError("Choices must not run inference"),
            ),
        ):
            response = client.get(
                f"/api/v1/projects/{self.project.id}/filter-values",
                params={"column": "property:molecular_weight"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["kind"], "number")
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["empty_count"], 0)

    def test_invalid_columns_color_and_bounded_choices_are_rejected(self):
        with self.client() as client:
            base = f"/api/v1/projects/{self.project.id}"
            for params in (
                {"column": "foreign"},
                {"column": "compound", "page_size": 201},
                {"column": "compound", "search": "x" * 501},
            ):
                response = client.get(base + "/filter-values", params=params)
                self.assertEqual(response.status_code, 422, response.text)
            for params in (
                {"sort_column": "compound", "sort_band": "strong"},
                {
                    "column_filters": json.dumps(
                        [{"column": "compound", "op": "band", "value": "strong"}]
                    )
                },
                {
                    "column_filters": json.dumps(
                        [
                            {
                                "column": "compound",
                                "op": "in",
                                "values": [],
                                "include_empty": "false",
                            }
                        ]
                    )
                },
            ):
                response = client.get(base + "/results", params=params)
                self.assertEqual(response.status_code, 422, response.text)

    def test_blank_selection_has_same_result_and_export(self):
        with self.client() as client:
            base = f"/api/v1/projects/{self.project.id}"
            params = {
                "column_filters": json.dumps(
                    [
                        {
                            "column": "property:molecular_weight",
                            "op": "in",
                            "values": [],
                            "include_empty": True,
                        }
                    ]
                )
            }
            visible = client.get(base + "/results", params=params)
            exported = client.post(
                base + "/export",
                params=params,
                json={"format": "json", "compound_ids": []},
            )
            self.assertEqual(visible.status_code, 200, visible.text)
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertEqual(
                [item["id"] for item in visible.json()["items"]],
                [item["id"] for item in exported.json()["items"]],
            )
