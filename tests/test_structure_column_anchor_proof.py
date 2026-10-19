"""Registered physical headers cannot be replaced by saved confidence flags."""

import json
import unittest

from test_structure_column_anchors import ruled_first_then_unruled
from test_unruled_continuation_proof import rewrite_continuation
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.activity_header_evidence import proof_id
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.errors import WebError


def column_anchor(payload):
    return next(
        s for s in payload["source_sections"] if s["role"] == "structure_column_anchor"
    )


def rehash_column_anchor(payload, section):
    old = section["region_id"]
    section["region_id"] = proof_id(section["source"])
    for row in [
        *payload["compound_catalog"]["entries"],
        *payload["compound_catalog"]["entries"],
    ]:
        ownership = (row.get("numbered_table_cell_evidence") or {}).get(
            "column_ownership", {}
        )
        if ownership.get("source_anchor_id") == old:
            ownership["source_anchor_id"] = section["region_id"]
    for child in payload["source_sections"]:
        header = child.get("source", {}).get("header_scope", {})
        if header.get("parent_region_id") == old:
            header["parent_region_id"] = section["region_id"]
            rewrite_continuation(payload, child)
    payload["source_reference_scope"] = reference_scope(
        payload["source_sections"],
        payload["source_reference_scope"]["original_pdf_sha256"],
    )
    payload["source_issues"] = []


class StructureColumnAnchorProofTests(UnruledStructureControls, unittest.TestCase):
    def test_source_with_only_an_id_or_only_a_drawing_cannot_clear_its_gap(self):
        for changes in ({"missing_label": 0}, {"missing_graph": 0}):
            with self.subTest(changes=changes):
                _, payload = self.run_binding(
                    ["73", "28"], mutate_page=ruled_first_then_unruled, **changes
                )
                payload["source_issues"] = []
                self.assertTrue(
                    reference_issues(payload, payload["compound_catalog"]["entries"])
                )
                self.assertTrue(coverage_errors(payload))

    def test_rehashed_competing_cell_diagram_cannot_keep_a_confirmed_binding(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        section = column_anchor(payload)
        first = section["source"]["page_diagrams"][0]
        section["source"]["page_diagrams"].append(
            {"id": "RIVAL", "bbox": first["bbox"]}
        )
        rehash_column_anchor(payload, section)
        self.assert_rejected(payload)

    def test_omitted_physical_row_cannot_become_clean_partial_success(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        rows = payload["compound_catalog"]["entries"]
        rows[:] = [row for row in rows if row["cpd"] != "Compound 73"]
        payload["source_issues"] = []
        payload["compound_catalog"]["numbered_compounds"] = 3
        payload["compound_catalog"]["source_observations"] = 3
        payload["final_bindings_count"] = 3
        payload["strict_coverage"] = {
            "expected_cpds": [
                row["cpd"] for row in payload["compound_catalog"]["entries"]
            ],
            "expected_structure_ids": [
                row["structure_id"] for row in payload["compound_catalog"]["entries"]
            ],
            "catalog_count": 3,
            "unresolved_sources": [],
        }
        self.assertTrue(
            reference_issues(payload, payload["compound_catalog"]["entries"])
        )
        self.assertTrue(coverage_errors(payload))

    def assert_rejected(self, payload):
        with self.assertRaises(ValueError):
            reference_issues(payload, payload["compound_catalog"]["entries"])
        with self.assertRaises(ValueError):
            read_catalog_entries(payload)
        with self.assertRaises(ValueError):
            coverage_errors(payload)
        with self.assertRaises(WebError):
            read_compound_catalog(payload, payload["compound_catalog"]["entries"])

    def test_serialized_physical_and_logical_sources_share_real_saved_consumers(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        payload = json.loads(json.dumps(payload))
        self.assertEqual(len(read_catalog_entries(payload)[0]), 4)
        self.assertEqual(
            len(
                read_compound_catalog(payload, payload["compound_catalog"]["entries"])[
                    0
                ]
            ),
            4,
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_removing_the_original_header_cannot_keep_its_cells_or_continuation(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        payload["source_sections"] = [
            s
            for s in payload["source_sections"]
            if s["role"] != "structure_column_anchor"
        ]
        payload["source_reference_scope"] = reference_scope(
            payload["source_sections"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )
        payload["source_issues"] = []
        self.assert_rejected(payload)

    def test_rehashed_header_root_cannot_drop_a_proved_original_diagram(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        section = column_anchor(payload)
        section["source"]["page_diagrams"].pop(0)
        rehash_column_anchor(payload, section)
        self.assert_rejected(payload)

    def test_valid_label_reading_must_still_match_the_complete_original_context(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        for row in [
            *payload["compound_catalog"]["entries"],
            *payload["compound_catalog"]["entries"],
        ]:
            evidence = row["numbered_table_cell_evidence"]
            if evidence.get("kind") == "original_ruled_columns":
                evidence["observations"][0]["source_observation"]["tokens"][0]["x"] += 1
        self.assert_rejected(payload)

    def test_cleared_scope_pointer_does_not_downgrade_current_original_cells(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        for row in [
            *payload["compound_catalog"]["entries"],
            *payload["compound_catalog"]["entries"],
        ]:
            evidence = row["numbered_table_cell_evidence"]
            if evidence.get("kind") == "original_ruled_columns":
                evidence["column_ownership"].pop("source_anchor_id")
        self.assert_rejected(payload)
