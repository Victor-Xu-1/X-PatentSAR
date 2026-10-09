"""Synthetic lossless header/grid controls; no patent-specific fixture data."""

from __future__ import annotations

import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_coordinates import (
    cell_text,
    extract_coordinate_tables,
    parse_grid,
)
from patent_sar_extractor.core.activity_headers import (
    context_from_text,
    grid_schema,
    infer_value_keys,
)
from patent_sar_extractor.core.activity_models import (
    ColumnGroup,
    GridSchema,
    TableContext,
)
from patent_sar_extractor.core.activity_text import parse_segment
from patent_sar_extractor.core.table_cells import CellReading
from patent_sar_extractor.web.activity_columns import ActivityColumnCatalog
from patent_sar_extractor.web.artifacts import _activities

CONTEXT = TableContext("Table 83", "Table 83. Activity assay", "MET", "binding")


def observed_grid(matrix, *, context=CONTEXT, schema=None, native=True):
    """Controlled page tokens go through the real physical-cell parser."""
    region = {
        "xs": [20 + 140 * column for column in range(len(matrix[0]) + 1)],
        "ys": [60 + 30 * row for row in range(len(matrix) + 1)],
    }
    tokens = [
        {"text": value, "x": region["xs"][col] + 50, "y": region["ys"][row] + 15}
        for row, cells in enumerate(matrix)
        for col, value in enumerate(cells)
        if value
    ]
    schema = schema or grid_schema(context, matrix)
    if schema is None:
        raise AssertionError("Expected a recognized activity grid")
    with fitz.open() as doc:
        page = doc.new_page(width=900)
        if native:
            page.insert_text((20, 25), "native control")
        rows = parse_grid(page, 1, tokens, region, schema)
    return schema, rows


class ActivityHeaderGridTests(unittest.TestCase):
    def test_actual_caption_and_body_survive_trailing_paragraph_number(self):
        source = "Table 83. MET cellular binding\nAssay: enzyme\n[00831]"
        context = context_from_text("[00831]", source)
        self.assertEqual(context.table_id, "Table 83")
        self.assertEqual(context.caption, "Table 83. MET cellular binding")
        self.assertEqual(context.assay, "enzyme")
        self.assertEqual(context.raw_caption, "Table 83. MET cellular binding")
        self.assertEqual(context.body_text, "Assay: enzyme\n[00831]")
        self.assertEqual(context.raw_context, source)

    def test_table_reference_in_body_does_not_replace_caption_or_supply_old_target(
        self,
    ):
        source = "Table 82. Target: ALK; Assay: binding\nTable 83. Cellular activity\n[00831] See Table 82."
        context = context_from_text("[00831] See Table 82.", source)
        self.assertEqual(context.table_id, "Table 83")
        self.assertEqual(context.caption, "Table 83. Cellular activity")
        self.assertIsNone(context.target)
        self.assertEqual(context.assay, "Cellular activity")
        self.assertEqual(context.raw_context, source)

    def test_paragraph_number_alone_is_not_an_assay_or_target(self):
        context = context_from_text("[00831]", "[00831]")
        self.assertIsNone(context.assay)
        self.assertIsNone(context.target)
        self.assertEqual(context.raw_context, "[00831]")

    def test_standalone_table_label_keeps_following_caption_title(self):
        source = "Table 83.\nCellular binding activity\n[00831] Local experimental body"
        context = context_from_text(source, source)
        self.assertEqual(context.caption, "Table 83. Cellular binding activity")
        self.assertEqual(context.raw_caption, "Table 83.\nCellular binding activity")
        self.assertEqual(context.body_text, "[00831] Local experimental body")
        self.assertEqual(context.assay, "Cellular binding activity")

    def test_attached_metric_suffixes_keep_both_values_and_contexts(self):
        headers = ["No.", "METHiBiTEC50 (nM)", "LU-7ProlifEC50 (nM)"]
        _, rows = observed_grid([headers, ["7B", "1.2", "3.4"]])
        self.assertEqual(
            rows[0].activity_values,
            {"METHiBiT EC50 (nM)": "1.2", "LU-7Prolif EC50 (nM)": "3.4"},
        )
        self.assertFalse(rows[0].needs_review)
        self.assertEqual(
            [c["raw_header"] for c in rows[0].activity_sources[0]["cells"]], headers
        )
        self.assertEqual(rows[0].activity_sources[0]["target"], "MET")

    def test_ocr_spacing_subscripts_and_separate_units_are_canonicalized(self):
        for raw, expected in (
            ("JAK2 I C 5 0 ( n M )", "JAK2 IC50 (nM)"),
            ("BTK DC₅₀\n（µ M）", "BTK DC50 (µM)"),
            ("ABL1 pIC_50", "ABL1 pIC50 (unit unknown)"),
            ("CDK9 E C\n5 O (μM)", "CDK9 EC50 (μM)"),
            ("MAPK D_max (%)", "MAPK Dmax (%)"),
            ("JAK2 IC50\nnM", "JAK2 IC50 (nM)"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(infer_value_keys("", raw, 1), [expected])

    def test_no_boundary_relaxation_for_short_or_embedded_nonmetrics(self):
        for raw in ("CLONE (nM)", "SHIFT (nM)", "EC500 (nM)", "MYEC50Gene (nM)"):
            with self.subTest(raw=raw):
                keys = infer_value_keys("Target: EGFR; IC50 (nM)", raw, 1)
                self.assertIn("unknown", keys[0].lower())
                self.assertNotIn("IC50", keys[0])

    def test_explicit_unknown_header_and_unit_are_preserved_not_guessed(self):
        headers = ["No.", "Novel signal (ng/mL)", "Other signal"]
        schema, rows = observed_grid([headers, ["8", "≤ 2", "A2"]])
        self.assertEqual(len(rows[0].activity_values), 2)
        self.assertEqual(list(rows[0].activity_values.values()), ["≤ 2", "A2"])
        self.assertTrue(rows[0].needs_review)
        self.assertTrue(all("unknown" in k.lower() for k in rows[0].activity_values))
        activities = _activities(asdict(rows[0]), page_count=1)
        self.assertEqual([a.unit for a in activities], ["ng/mL", "unit unknown"])
        self.assertEqual(schema.raw_headers, tuple(headers))

    def test_duplicate_known_fields_are_unique_stable_and_unit_compatible(self):
        matrix = [["No.", "BTK IC50 (nM)", "BTK IC50 (nM)"], ["9", "<2", ">3"]]
        schema, rows = observed_grid(matrix)
        self.assertEqual(len(rows[0].activity_values), 2)
        self.assertEqual(list(rows[0].activity_values.values()), ["<2", ">3"])
        self.assertEqual(schema, grid_schema(CONTEXT, matrix))
        projected = _activities(asdict(rows[0]), page_count=1)
        self.assertEqual([a.unit for a in projected], ["nM", "nM"])
        catalog = ActivityColumnCatalog()
        catalog.observe(projected, compound_id="controlled-source")
        self.assertEqual(len(catalog.columns()), 2)
        self.assertEqual(len({c.id for c in catalog.columns()}), 2)
        cells = rows[0].activity_sources[0]["cells"][1:]
        self.assertEqual([c["physical_column"] for c in cells], [1, 2])
        self.assertNotEqual(cells[0]["bbox"], cells[1]["bbox"])

    def test_legacy_duplicate_schema_is_lossless_even_without_header_metadata(self):
        schema = GridSchema(CONTEXT, (ColumnGroup(0, ((1, "Grade"), (2, "Grade"))),), 1)
        _, rows = observed_grid(
            [["No.", "Grade", "Grade"], ["10", "++", "+++ "]], schema=schema
        )
        self.assertEqual(len(rows[0].activity_values), 2)
        self.assertEqual(list(rows[0].activity_values.values()), ["++", "+++"])

    def test_legacy_value_label_cannot_replace_the_printed_id_field(self):
        schema = GridSchema(CONTEXT, (ColumnGroup(0, ((1, "compound_id"),)),), 1)
        _, rows = observed_grid([["No.", "Unknown"], ["10A", "A2"]], schema=schema)
        self.assertEqual(rows[0].cpd, "Compound 10A")
        self.assertEqual(list(rows[0].activity_values.values()), ["A2"])
        self.assertTrue(rows[0].needs_review)

    def test_unknown_multiline_unit_is_kept_as_header_not_guessed_metric(self):
        schema, rows = observed_grid(
            [["No.", "Unknown signal"], ["", "(n M)"], ["10B", "< 2"]]
        )
        self.assertEqual(schema.first_data_row, 2)
        self.assertEqual(list(rows[0].activity_values.values()), ["< 2"])
        self.assertEqual(_activities(asdict(rows[0]))[0].unit, "nM")
        self.assertTrue(rows[0].needs_review)

    def test_unknown_blank_columns_do_not_collide_or_shift_missing_values(self):
        _, rows = observed_grid([["No.", "", "", "Dmax (%)"], ["11", "", "ND", "84%"]])
        self.assertEqual(len(rows[0].activity_values), 3)
        self.assertEqual(list(rows[0].activity_values.values()), ["", "ND", "84%"])
        self.assertTrue(rows[0].needs_review)

    def test_multiline_physical_header_rows_are_not_read_as_compound_data(self):
        matrix = [
            ["No.", "JAK2 binding", "BTK degradation"],
            ["", "IC₅₀", "Dmax"],
            ["", "(n M)", "(%)"],
            ["12A", "N/A", "88"],
        ]
        schema, rows = observed_grid(matrix)
        self.assertEqual(schema.first_data_row, 3)
        self.assertEqual(
            rows[0].activity_values,
            {"JAK2 binding IC50 (nM)": "N/A", "BTK degradation Dmax (%)": "88"},
        )
        self.assertEqual(schema.raw_headers[1], "JAK2 binding\nIC₅₀\n(n M)")

    def test_split_id_header_joins_only_same_physical_column(self):
        schema, rows = observed_grid(
            [["Compound", "JAK2"], ["No.", "IC50 (nM)"], ["13", "1.8"]]
        )
        self.assertEqual(schema.first_data_row, 2)
        self.assertEqual(rows[0].activity_values, {"JAK2 IC50 (nM)": "1.8"})

    def test_header_scan_does_not_consume_a_missing_id_data_row(self):
        matrix = [["No.", "IC50 (nM)"], ["", "2.5"], ["14", "3"]]
        schema = grid_schema(CONTEXT, matrix)
        self.assertEqual(schema.first_data_row, 1)
        with self.assertRaisesRegex(RuntimeError, "Unresolved compound ID"):
            observed_grid(matrix, schema=schema)

    def test_header_scan_does_not_skip_unit_shaped_data_with_missing_id(self):
        matrix = [["No.", "IC50 (nM)"], ["", "nM"], ["14", "3"]]
        self.assertEqual(grid_schema(CONTEXT, matrix).first_data_row, 1)

    def test_header_scan_does_not_skip_metric_shaped_data_with_missing_id(self):
        matrix = [["No.", "IC50 (nM)"], ["", "IC50"], ["14", "3"]]
        self.assertEqual(grid_schema(CONTEXT, matrix).first_data_row, 1)

    def test_multiple_metrics_in_one_cell_remain_explicitly_unknown(self):
        _, rows = observed_grid([["No.", "IC50 (nM) / Kd (uM)"], ["22", "A"]])
        self.assertIn("unknown", next(iter(rows[0].activity_values)).lower())
        self.assertEqual(list(rows[0].activity_values.values()), ["A"])
        self.assertTrue(rows[0].needs_review)

    def test_delimited_mixed_known_and_unknown_headers_do_not_shift(self):
        rows = parse_segment(
            "Table 83 assay",
            "No.\tUnknown signal (pM)\tIC50 (nM)\n23\tND\t< 4",
            page_no=1,
        )
        self.assertEqual(list(rows[0].activity_values.values()), ["ND", "< 4"])
        keys = list(rows[0].activity_values)
        self.assertIn("unknown", keys[0].lower())
        self.assertEqual(keys[1], "IC50 (nM)")
        self.assertTrue(rows[0].needs_review)

    def test_recognized_field_with_trailing_context_keeps_actual_unit(self):
        self.assertEqual(
            infer_value_keys("", "BTK IC50 (nM) (biochemical)", 1),
            ["BTK IC50 (biochemical) (nM)"],
        )

    def test_stable_suffixes_cannot_collide_with_printed_column_annotation(self):
        _, rows = observed_grid(
            [
                ["No.", "IC50 (nM)", "IC50 (nM)", "IC50 [column 1] (nM)"],
                ["24", "2", "3", "4"],
            ]
        )
        self.assertEqual(len(rows[0].activity_values), 3)
        self.assertEqual(list(rows[0].activity_values.values()), ["2", "3", "4"])
        self.assertEqual([a.unit for a in _activities(asdict(rows[0]))], ["nM"] * 3)

    def test_single_id_in_middle_does_not_drop_preceding_activity_column(self):
        _, rows = observed_grid([["Dmax (%)", "No.", "IC50 (nM)"], ["85", "25", "<5"]])
        self.assertEqual(rows[0].activity_values, {"Dmax (%)": "85", "IC50 (nM)": "<5"})

    def test_invalid_schema_ownership_and_ragged_headers_fail_explicitly(self):
        for positions in (
            ((1, "Grade"), (1, "Other")),
            ((1, "Grade"),),
            ((1, "Grade"), (3, "Other")),
        ):
            with self.subTest(positions=positions):
                schema = GridSchema(CONTEXT, (ColumnGroup(0, positions),), 1)
                with self.assertRaisesRegex(ValueError, "physical column"):
                    observed_grid(
                        [["No.", "Grade", "Other"], ["26", "A", "B"]], schema=schema
                    )
        with self.assertRaisesRegex(ValueError, "physical column"):
            grid_schema(CONTEXT, [["No.", "IC50"], ["26", "1", "2"]])

    def test_native_classes_ranges_and_missing_markers_remain_raw_values(self):
        values = ["≤ 2", "A2", "++++", "1 ± 0.2", "ND", "not tested", "1-3", "garbled"]
        _, rows = observed_grid([["No.", *(["Grade"] * len(values))], ["27", *values]])
        self.assertEqual(list(rows[0].activity_values.values()), values)
        self.assertTrue(rows[0].needs_review)
        self.assertEqual(
            [
                c["observations"][0]["text"]
                for c in rows[0].activity_sources[0]["cells"]
            ][1:],
            values,
        )

    def test_explicit_unknown_grid_is_not_inferred_as_grade_from_caption(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (30, 80),
                "Table 83. Protein degradation by Western blot assay",
                fontsize=9,
            )
            xs, ys = [30, 200, 450], [100, 125, 150]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            for x, y, text in (
                (38, 115, "Compound No."),
                (208, 115, "Unknown endpoint (nM)"),
                (38, 140, "28"),
                (208, 140, "A"),
            ):
                page.insert_text((x, y), text, fontsize=9)
            result = extract_coordinate_tables(doc, [0])
        self.assertTrue(result.rows[0].needs_review)
        self.assertIn("unknown", next(iter(result.rows[0].activity_values)).lower())

    def test_half_open_cell_boundaries_never_drop_or_copy_near_rule_token(self):
        tokens = [{"text": "2", "x": 100, "y": 20}]
        self.assertEqual(cell_text(tokens, (0, 0, 100, 50)), "")
        self.assertEqual(cell_text(tokens, (100, 0, 200, 50)), "2")

    def test_cross_rule_word_is_retained_but_not_certified(self):
        matrix = [["No.", "IC50 (nM)"], ["29", "2"]]
        region = {"xs": [20, 160, 300], "ys": [60, 90, 120]}
        tokens = [
            {"text": "29", "x": 70, "y": 105},
            {"text": "2", "x": 165, "y": 105, "bbox": [155, 100, 175, 112]},
        ]
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((20, 25), "native control")
            row = parse_grid(page, 1, tokens, region, grid_schema(CONTEXT, matrix))[0]
        self.assertEqual(row.activity_values, {"IC50 (nM)": "2"})
        self.assertTrue(row.needs_review)

    def test_parallel_groups_keep_original_ids_and_ordinal_field_ownership(self):
        schema, rows = observed_grid(
            [["No.", "Novel signal", "No.", "Novel signal"], ["15A", "A", "15B", "B"]]
        )
        self.assertEqual([r.cpd for r in rows], ["Compound 15A", "Compound 15B"])
        self.assertEqual(
            schema.groups[0].value_columns[0][1], schema.groups[1].value_columns[0][1]
        )
        self.assertEqual(
            [list(r.activity_values.values()) for r in rows], [["A"], ["B"]]
        )

    def test_carried_schema_keeps_headers_and_does_not_borrow_units(self):
        schema = grid_schema(
            CONTEXT, [["No.", "Novel (pM)", "Other (uM)"], ["16", "4", "5"]]
        )
        _, rows = observed_grid(
            [["17", "6", "7"]], schema=replace(schema, first_data_row=0)
        )
        self.assertEqual(list(rows[0].activity_values.values()), ["6", "7"])
        self.assertEqual(
            [c["raw_header"] for c in rows[0].activity_sources[0]["cells"]][1:],
            ["Novel (pM)", "Other (uM)"],
        )
        self.assertTrue(rows[0].needs_review)

    def test_duplicate_text_headers_cannot_overwrite_values(self):
        rows = parse_segment(
            "Table 83 assay", "No. IC50 (nM) IC50 (nM)\n18 <2 >3", page_no=1
        )
        self.assertEqual(len(rows[0].activity_values), 2)
        self.assertEqual(list(rows[0].activity_values.values()), ["<2", ">3"])

    def test_scanned_raw_censored_value_is_not_replaced_by_scalar_ocr(self):
        matrix = [["No.", "IC50 (nM)"], ["19", "> 20"]]

        def reading(page, bounds, tokens, kind, native):
            value = "19" if kind == "id" else "20"
            return CellReading(
                value, bounds, [{"method": "cell_ocr", "text": value}], False
            )

        with patch(
            "patent_sar_extractor.core.activity_grid_cells.read_cell",
            side_effect=reading,
        ):
            _, rows = observed_grid(matrix, native=False)
        self.assertEqual(rows[0].activity_values, {"IC50 (nM)": "> 20"})
        self.assertTrue(rows[0].needs_review)
        self.assertIn(
            "> 20",
            [
                o["text"]
                for o in rows[0].activity_sources[0]["cells"][1]["observations"]
            ],
        )

    def test_one_multiline_cell_reconstructs_subscript_by_horizontal_order(self):
        tokens = [
            {"text": "50", "x": 55, "y": 24, "bbox": [50, 20, 60, 28]},
            {"text": "IC", "x": 42, "y": 20, "bbox": [35, 14, 49, 25]},
            {"text": "(nM)", "x": 48, "y": 38, "bbox": [35, 33, 61, 43]},
            {"text": "JAK2", "x": 48, "y": 9, "bbox": [35, 4, 61, 13]},
        ]
        raw = cell_text(tokens, (20, 0, 80, 50))
        self.assertEqual(raw, "JAK2\nIC 50\n(nM)")
        self.assertEqual(infer_value_keys("", raw, 1), ["JAK2 IC50 (nM)"])

    def test_unrelated_native_grid_uses_multiline_units_and_changed_layout(self):
        with fitz.open() as doc:
            page = doc.new_page(width=800, height=500)
            xs, ys = [40, 180, 410, 650], [100, 165, 200]
            page.insert_text(
                (40, 80), "Table 83. Target: JAK2; Assay: enzyme", fontsize=9
            )
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            for col, text in enumerate(
                ("Compound No.", "JAK2\nI C 5 0\n(n M)", "BTK\nK d\n(u M)")
            ):
                page.insert_text((xs[col] + 8, 115), text, fontsize=10)
            for col, text in enumerate(("21C", "<= 3", "5.1")):
                page.insert_text((xs[col] + 8, 187), text, fontsize=10)
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(
            result.rows[0].activity_values,
            {"JAK2 IC50 (nM)": "<= 3", "BTK Kd (uM)": "5.1"},
        )
        self.assertEqual(result.owned_pages, {0})
        self.assertFalse(result.rows[0].needs_review)

    def test_native_caption_body_and_header_provenance_are_kept_separately(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((60, 75), "Table 83. MET cellular binding", fontsize=9)
            page.insert_text((60, 90), "[00831]", fontsize=9)
            from tests.test_activity_parser_modules import draw_grid

            draw_grid(page, [["No.", "IC50 (nM)"], ["32", "2"]], caption="", top=120)
            row = extract_coordinate_tables(doc, [0]).rows[0]
        source = row.activity_sources[0]
        self.assertEqual(source["table_id"], "Table 83")
        self.assertEqual(source["assay"], "MET cellular binding")
        self.assertEqual(source["raw_caption"], "Table 83. MET cellular binding")
        self.assertIn("[00831]", source["body_text"])
        self.assertIn("[00831]", source["raw_context"])
        self.assertEqual(source["cells"][1]["raw_header"], "IC50 (nM)")


if __name__ == "__main__":
    unittest.main()
