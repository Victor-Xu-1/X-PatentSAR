"""Source count columns remain evidence, never potency or independent repeats."""

import unittest
from dataclasses import asdict

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import coverage_packet
from patent_sar_extractor.core.activity_header_identity import header_conflict
from patent_sar_extractor.core.activity_headers import grid_schema
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_text import parse_segment
from patent_sar_extractor.web.activity_columns import ActivityColumnCatalog
from patent_sar_extractor.web.artifacts import _activities
from tests.test_activity_header_grid import CONTEXT, observed_grid
from tests.test_activity_parser_modules import draw_grid


class ActivityMetadataTests(unittest.TestCase):
    def test_bare_n_preserves_fractional_parameter_without_inventing_sample_count(self):
        _, rows = observed_grid([["No.", "IC50 (nM)", "n"], ["73", "12.4", "1.5"]])
        self.assertFalse(rows[0].needs_review)
        cell = rows[0].activity_sources[0]["cells"][-1]
        self.assertEqual(cell["metadata_kind"], "reported_n")
        self.assertEqual(cell["value"], "1.5")
        self.assertNotIn("sample_count", str(cell))
        self.assertEqual(rows[0].activity_values, {"IC50 (nM)": "12.4"})

    def test_original_counts_are_not_measurements_or_web_activity_columns(self):
        schema, rows = observed_grid(
            [["No.", "IC50 (nM)", "n", "Replicates"], ["73", "12.4", "3", "2"]]
        )
        row = rows[0]
        self.assertEqual(row.activity_values, {"IC50 (nM)": "12.4"})
        self.assertFalse(row.needs_review)
        self.assertEqual(
            schema.groups[0].metadata_columns,
            ((2, "reported_n"), (3, "replicate_count")),
        )
        metadata = [
            c for c in row.activity_sources[0]["cells"] if c.get("role") == "metadata"
        ]
        self.assertEqual([c["value"] for c in metadata], ["3", "2"])
        self.assertEqual([c["raw_header"] for c in metadata], ["n", "Replicates"])
        self.assertEqual([c["physical_column"] for c in metadata], [2, 3])
        self.assertTrue(all(c["bbox"] and c["observations"] for c in metadata))
        projected = _activities(asdict(row), page_count=1)
        self.assertEqual(
            [(a.name, a.value) for a in projected], [("IC50 (nM)", "12.4")]
        )
        catalog = ActivityColumnCatalog()
        catalog.observe(projected, compound_id="source-control")
        self.assertEqual(len(catalog.columns()), 1)

    def test_repeated_groups_keep_each_count_in_its_original_physical_group(self):
        schema, rows = observed_grid(
            [
                ["No.", "IC50 (nM)", "n", "No.", "IC50 (nM)", "Replicates"],
                ["73", "12.4", "3", "58", "9.1", "2"],
            ]
        )
        self.assertEqual([r.cpd for r in rows], ["Compound 73", "Compound 58"])
        self.assertEqual(
            [list(r.activity_values.values()) for r in rows], [["12.4"], ["9.1"]]
        )
        self.assertEqual(
            [g.metadata_columns for g in schema.groups],
            [((2, "reported_n"),), ((5, "replicate_count"),)],
        )

    def test_metadata_does_not_renumber_duplicate_metric_physical_ordinals(self):
        _, rows = observed_grid(
            [["No.", "IC50 (nM)", "n", "IC50 (nM)"], ["73", "12.4", "3", "9.1"]]
        )
        self.assertEqual(
            list(rows[0].activity_values),
            ["IC50 [column 1] (nM)", "IC50 [column 3] (nM)"],
        )

    def test_unknown_count_shaped_or_metric_headers_are_not_silently_removed(self):
        for header in ("n (%)", "nM", "NIG IC50 (nM)", "Novel count signal"):
            with self.subTest(header=header):
                _, rows = observed_grid([["No.", header], ["73", "3"]])
                self.assertEqual(list(rows[0].activity_values.values()), ["3"])
                self.assertFalse(
                    any(
                        c.get("role") == "metadata"
                        for c in rows[0].activity_sources[0]["cells"]
                    )
                )

    def test_count_only_source_is_not_an_activity_schema(self):
        self.assertIsNone(grid_schema(CONTEXT, [["No.", "n"], ["73", "3"]]))

    def test_metadata_identity_cannot_be_overwritten_by_endpoint_consensus(self):
        for old, fresh in (
            ("n", "IC50 (nM)"),
            ("IC50 (nM)", "n"),
            ("Unknown signal", "n"),
            ("n", "Replicates"),
        ):
            with self.subTest(old=old, fresh=fresh):
                self.assertTrue(header_conflict(old, fresh))
        self.assertFalse(header_conflict("n", "N"))
        self.assertFalse(header_conflict("Replicates", "Number of replicates"))

    def test_invalid_original_count_is_retained_as_review_not_a_new_endpoint(self):
        _, rows = observed_grid(
            [["No.", "IC50 (nM)", "Sample size"], ["73", "12.4", "2.5"]]
        )
        self.assertEqual(rows[0].activity_values, {"IC50 (nM)": "12.4"})
        self.assertTrue(rows[0].needs_review)
        self.assertEqual(rows[0].activity_sources[0]["cells"][-1]["value"], "2.5")

    def test_delimited_original_text_keeps_count_positions_and_values(self):
        for delimiter in ("|", "\t"):
            source = (
                delimiter.join(("No.", "n", "IC50 (nM)"))
                + "\n"
                + delimiter.join(("73", "3", "12.4"))
            )
            with self.subTest(delimiter=delimiter):
                row = parse_segment("Table 87. Binding activity", source, page_no=1)[0]
                self.assertEqual(row.activity_values, {"IC50 (nM)": "12.4"})
                self.assertFalse(row.needs_review)
                metadata = [
                    c
                    for c in row.activity_sources[0]["cells"]
                    if c.get("role") == "metadata"
                ]
                self.assertEqual([c["value"] for c in metadata], ["3"])
                self.assertEqual(metadata[0]["physical_column"], 1)

    def test_real_native_coordinate_adapter_and_adjacent_continuation_keep_roles(self):
        with fitz.open() as doc:
            draw_grid(doc.new_page(), [["No.", "IC50 (nM)", "n"], ["73", "12.4", "3"]])
            draw_grid(
                doc.new_page(),
                [["58", "9.1", "2"], ["42", "1.8", "4"]],
                caption="",
                top=75,
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(
            [r.cpd for r in result.rows], ["Compound 73", "Compound 58", "Compound 42"]
        )
        self.assertEqual(
            [r.activity_values for r in result.rows],
            [{"IC50 (nM)": "12.4"}, {"IC50 (nM)": "9.1"}, {"IC50 (nM)": "1.8"}],
        )
        self.assertFalse(any(r.needs_review for r in result.rows))

    def test_real_native_transposed_count_row_is_not_an_endpoint(self):
        with fitz.open() as doc:
            draw_grid(
                doc.new_page(),
                [
                    ["", "Compound 73", "Compound 58"],
                    ["IC50 (nM)", "12.4", "9.1"],
                    ["n", "3", "2"],
                ],
            )
            parsed = extract_coordinate_tables(doc, [0])
            rows = parsed.rows
        self.assertEqual([r.cpd for r in rows], ["Compound 73", "Compound 58"])
        self.assertEqual(
            [list(r.activity_values.values()) for r in rows], [["12.4"], ["9.1"]]
        )
        self.assertFalse(any(r.needs_review for r in rows))
        self.assertEqual(
            [r.activity_sources[0]["cells"][-1]["value"] for r in rows], ["3", "2"]
        )
        from patent_sar_extractor.contracts import (
            ACTIVITY_SCHEMA,
            ACTIVITY_SCHEMA_VERSION,
            artifact_identity,
        )

        self.assertEqual(
            activity_evidence_errors(
                {
                    **artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
                    "rows": [asdict(row) for row in rows],
                    "coverage": coverage_packet([0], parsed.coverage, rows),
                },
                [0],
            ),
            [],
        )

    def test_persisted_count_disagreement_remains_failure_without_review_boolean(self):
        from patent_sar_extractor.core.activity_metadata import (
            mark_metadata,
            metadata_evidence_errors,
        )

        cell = mark_metadata(
            {
                "field": "n",
                "raw_header": "n",
                "value": "3",
                "physical_column": 2,
                "observations": [
                    {"method": "native_cell", "text": "3"},
                    {"method": "cell_ocr_400dpi", "text": "8", "confidence": 0.95},
                ],
            },
            "reported_n",
        )
        self.assertEqual(cell["metadata_status"], "unresolved")
        self.assertTrue(
            metadata_evidence_errors(
                [
                    {
                        "cpd": "Compound 73",
                        "needs_review": False,
                        "activity_sources": [{"cells": [cell]}],
                    }
                ]
            )
        )

    def test_forged_count_role_cannot_hide_a_metric(self):
        from patent_sar_extractor.core.activity_metadata import (
            mark_metadata,
            metadata_cell,
        )
        from patent_sar_extractor.web.activity_provenance import cell_evidence
        from patent_sar_extractor.web.errors import WebError

        cell = mark_metadata(
            {
                "field": "n",
                "raw_header": "n",
                "value": "3",
                "physical_column": 2,
                "observations": [{"method": "native_cell", "text": "3"}],
            },
            "reported_n",
        )
        cell["raw_header"] = "IC50 (nM)"
        with self.assertRaises(ValueError):
            metadata_cell(cell)
        with self.assertRaises(WebError):
            cell_evidence(cell)

    def test_metadata_geometry_ownership_requires_exact_original_header(self):
        from dataclasses import replace

        from patent_sar_extractor.core.activity_grid_cells import validate_grid
        from patent_sar_extractor.core.activity_models import ColumnGroup

        schema, _ = observed_grid([["No.", "IC50 (nM)", "n"], ["73", "12.4", "3"]])
        region = {"xs": [20, 160, 300, 440], "ys": [60, 90, 120]}
        for groups, headers in (
            (
                (ColumnGroup(0, ((1, "IC50 (nM)"),), ((1, "reported_n"),)),),
                schema.raw_headers,
            ),
            (schema.groups, ("No.", "IC50 (nM)", "Dmax (%)")),
            (schema.groups, ("No.",)),
        ):
            with (
                self.subTest(groups=groups, headers=headers),
                self.assertRaises(ValueError),
            ):
                validate_grid(
                    region, replace(schema, groups=groups, raw_headers=headers)
                )

    def test_low_confidence_count_cannot_establish_metadata_proof(self):
        from patent_sar_extractor.core.activity_metadata import mark_metadata

        cell = mark_metadata(
            {
                "field": "n",
                "raw_header": "n",
                "value": "3",
                "physical_column": 2,
                "observations": [
                    {"method": "cell_ocr_400dpi", "text": "3", "confidence": 0.4}
                ],
            },
            "reported_n",
        )
        self.assertEqual(cell["metadata_status"], "unresolved")
        cell = mark_metadata(
            {
                "field": "n",
                "raw_header": "n",
                "value": "3",
                "physical_column": 2,
                "observations": [
                    {"method": "page_ocr_cell", "text": "3"},
                    {"method": "cell_ocr_400dpi", "text": "3", "confidence": 0.4},
                ],
            },
            "reported_n",
        )
        self.assertEqual(cell["metadata_status"], "unresolved")

    def test_explicit_original_missing_count_is_not_missing_potency_or_zero(self):
        for value in ("", "ND", "N/A"):
            with self.subTest(value=value):
                _, rows = observed_grid(
                    [["No.", "IC50 (nM)", "n"], ["73", "12.4", value]]
                )
                self.assertEqual(rows[0].activity_values, {"IC50 (nM)": "12.4"})
                self.assertFalse(rows[0].needs_review)
                self.assertEqual(
                    rows[0].activity_sources[0]["cells"][-1]["value"], value
                )
                self.assertEqual(
                    rows[0].activity_sources[0]["cells"][-1]["metadata_status"],
                    "missing",
                )
        row = parse_segment(
            "Table 87. Binding activity", "No.\tn\tIC50 (nM)\n73\t\t12.4", page_no=1
        )[0]
        self.assertFalse(row.needs_review)
        self.assertEqual(row.activity_values, {"IC50 (nM)": "12.4"})

    def test_unpositioned_counts_do_not_invent_column_assignment(self):
        row = parse_segment(
            "Table 87. Binding activity", "No. IC50 (nM)\nn\n73 12.4 3", page_no=1
        )[0]
        self.assertTrue(row.needs_review)
        self.assertTrue(all(not value for value in row.activity_values.values()))
        self.assertIn("n", row.activity_sources[0]["raw_header"])

    def test_unknown_role_and_measurement_metadata_contamination_are_rejected(self):
        from patent_sar_extractor.core.activity_join import activity_order_and_map
        from patent_sar_extractor.core.activity_metadata import metadata_cell

        for name in ("n", "Replicates", "metadata:sample_count"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                activity_order_and_map(
                    [{"cpd": "Compound 73", "activity_values": {name: "3"}}]
                )
            from patent_sar_extractor.web.errors import WebError

            with self.subTest(name=name), self.assertRaises(WebError):
                _activities({"cpd": "Compound 73", "activity_values": {name: "3"}})
        with self.assertRaises(ValueError):
            metadata_cell({"field": "metadata:sample_count", "value": "3"})
