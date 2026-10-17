"""Saved unruled sources must conserve originals through every real consumer."""

import copy
import json
import unittest

from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.activity_header_evidence import proof_id
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.unruled_structure_layout import region_plan
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.errors import WebError


def region_section(payload):
    return next(
        s for s in payload["source_sections"] if s["role"] == "unruled_structure_region"
    )


def rehash_region(payload):
    section = region_section(payload)
    old = section["region_id"]
    section["region_id"] = proof_id(section["source"])
    for row in [*payload["compound_catalog"]["entries"], *payload["final_bindings"]]:
        evidence = row.get("numbered_table_cell_evidence", {})
        if evidence.get("source_region_id") == old:
            evidence["source_region_id"] = section["region_id"]
    payload["source_reference_scope"] = reference_scope(
        payload["source_sections"],
        payload["source_reference_scope"]["original_pdf_sha256"],
    )
    payload["source_issues"] = []


class UnruledStructureProofTests(UnruledStructureControls, unittest.TestCase):
    def assert_rejected(self, payload):
        entries = payload["compound_catalog"]["entries"]
        with self.assertRaises(ValueError):
            reference_issues(payload, entries)
        with self.assertRaises(ValueError):
            read_catalog_entries(payload)
        with self.assertRaises(ValueError):
            coverage_errors(payload)
        with self.assertRaises(WebError):
            read_compound_catalog(payload, payload["final_bindings"])

    def test_serialized_complete_source_replays_without_success_flags(self):
        _, payload = self.run_binding(["I-009A", "28"])
        payload = json.loads(json.dumps(payload))
        entries, _ = read_catalog_entries(payload)
        self.assertEqual(
            [row["cpd"] for row in entries], ["Compound 28", "Compound I-009A"]
        )
        self.assertEqual(reference_issues(payload, entries), [])
        self.assertEqual(coverage_errors(payload), [])
        self.assertEqual(
            len(read_compound_catalog(payload, payload["final_bindings"])[0]), 2
        )

    def test_unruled_only_scope_infers_the_same_document_identity(self):
        _, payload = self.run_binding(["73", "28"])
        self.assertEqual(
            reference_scope(payload["source_sections"])["original_pdf_sha256"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )

    def test_removed_label_cannot_hide_behind_rehashed_region_or_cleared_findings(self):
        _, payload = self.run_binding(["73", "28"])
        region_section(payload)["source"]["labels"].pop()
        rehash_region(payload)
        self.assert_rejected(payload)

    def test_label_packet_cannot_disagree_with_retained_complete_body_source(self):
        _, payload = self.run_binding(["73", "28"])
        source = region_section(payload)["source"]
        observed = source["labels"][0]["observations"][0]
        observed["source_observation"]["tokens"][0]["bbox"][0] += 1
        rehash_region(payload)
        self.assert_rejected(payload)

    def test_new_ambiguous_graph_cannot_retain_previously_proved_binding(self):
        _, payload = self.run_binding(["73", "28"])
        source = region_section(payload)["source"]
        source["diagrams"].append(
            {**copy.deepcopy(source["diagrams"][0]), "id": "overlap"}
        )
        rehash_region(payload)
        self.assert_rejected(payload)

    def test_original_unruled_ledger_cannot_be_removed_or_downgraded(self):
        _, original = self.run_binding(["73", "28"])
        for mutation in ("removed", "downgraded", "foreign"):
            payload = copy.deepcopy(original)
            if mutation == "removed":
                payload["source_sections"] = []
                payload["source_reference_scope"] = reference_scope(
                    [], original["source_reference_scope"]["original_pdf_sha256"]
                )
            elif mutation == "downgraded":
                scope = payload["source_reference_scope"]
                scope["version"] = 5
                scope.pop("unruled_region_ids")
            else:
                region_section(payload)["source"]["header_scope"][
                    "original_pdf_sha256"
                ] = "f" * 64
                rehash_region(payload)
            with self.subTest(mutation=mutation):
                self.assert_rejected(payload)

    def test_historical_reader_cannot_ignore_a_current_typed_region_with_no_scope(self):
        _, payload = self.run_binding(["73", "28"])
        payload.pop("source_reference_scope")
        with self.assertRaises(ValueError):
            reference_issues(
                payload, payload["compound_catalog"]["entries"], required=False
            )

    def test_diagram_outside_original_page_is_invalid_not_only_unmatched(self):
        _, payload = self.run_binding(["73", "28"])
        source = region_section(payload)["source"]
        source["diagrams"][0]["bbox"][2] = 1000
        with self.assertRaises(ValueError):
            region_plan(source)


if __name__ == "__main__":
    unittest.main()
