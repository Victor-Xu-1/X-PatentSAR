"""A saved continuation cannot invent an anchor or hide conflicting originals."""

import copy
import json
import unittest

from test_unruled_continuation import continued_page, same_page_part
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.activity_header_evidence import proof_id
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_cell_tokens import cell_text
from patent_sar_extractor.core.unruled_continuation_titles import continuation_nominees
from patent_sar_extractor.core.unruled_structure_layout import (
    pair_evidence,
    region_plan,
)
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.errors import WebError


def continuation_section(payload):
    return next(
        s
        for s in payload["source_sections"]
        if s.get("source", {}).get("header_scope", {}).get("kind")
        == "continued_unruled_columns"
    )


def rewrite_continuation(payload, section):
    old = section["region_id"]
    section["region_id"] = proof_id(section["source"])
    _roles, assignments, _issues = region_plan(section["source"])
    expected = {
        p["structure_id"]: p
        for a, b in assignments
        for p in [pair_evidence(section["source"], section["region_id"], a, b)]
    }
    for row in [*payload["compound_catalog"]["entries"], *payload["final_bindings"]]:
        evidence = row.get("numbered_table_cell_evidence", {})
        if evidence.get("source_region_id") == old:
            row["numbered_table_cell_evidence"] = copy.deepcopy(
                expected[row["structure_id"]]
            )
    payload["source_reference_scope"] = reference_scope(
        payload["source_sections"],
        payload["source_reference_scope"]["original_pdf_sha256"],
    )
    payload["source_issues"] = []


class UnruledContinuationProofTests(UnruledStructureControls, unittest.TestCase):
    def test_only_the_same_physical_literal_caption_is_a_shared_nomination(self):
        def token(text, bounds):
            return {
                "text": text,
                "bbox": bounds,
                "x": (bounds[0] + bounds[2]) / 2,
                "y": (bounds[1] + bounds[3]) / 2,
            }

        source = [token("Table 12. Continued", [40, 35, 150, 48])]
        for text, bounds, count in (
            ("Table 12. Continued", [41, 36, 151, 49], 1),
            ("Table 12. Continued", [300, 35, 410, 48], 2),
            ("Table 13. Continued", [41, 36, 151, 49], 2),
            ("Table 12. Continued Intermediates", [41, 36, 151, 49], 2),
        ):
            with self.subTest(text=text, bounds=bounds):
                self.assertEqual(
                    len(
                        continuation_nominees(
                            source, [520, 720], native_tokens=[token(text, bounds)]
                        )
                    ),
                    count,
                )

    def assert_rejected(self, payload, message):
        with self.assertRaisesRegex(ValueError, message):
            reference_issues(payload, payload["compound_catalog"]["entries"])
        with self.assertRaises(ValueError):
            read_catalog_entries(payload)
        with self.assertRaises(ValueError):
            coverage_errors(payload)
        with self.assertRaises(WebError):
            read_compound_catalog(payload, payload["final_bindings"])

    def test_serialized_same_and_adjacent_page_sources_replay_in_real_consumers(self):
        for mutation in (same_page_part, continued_page):
            _, payload = self.run_binding(["73", "28"], mutate_page=mutation)
            payload = json.loads(json.dumps(payload))
            self.assertEqual(len(read_catalog_entries(payload)[0]), 4)
            self.assertEqual(
                len(read_compound_catalog(payload, payload["final_bindings"])[0]), 4
            )
            self.assertEqual(coverage_errors(payload), [])

    def test_rehashed_child_cannot_reference_an_unknown_parent(self):
        _, payload = self.run_binding(["73", "28"], mutate_page=continued_page)
        section = continuation_section(payload)
        section["source"]["header_scope"]["parent_region_id"] = "e" * 64
        rewrite_continuation(payload, section)
        self.assert_rejected(payload, "parent link")

    def test_registered_parent_cannot_be_removed_and_the_ledger_rehashed(self):
        _, payload = self.run_binding(["73", "28"], mutate_page=continued_page)
        payload["source_sections"] = [
            s
            for s in payload["source_sections"]
            if s.get("source", {}).get("header_scope", {}).get("kind")
            == "continued_unruled_columns"
        ]
        payload["source_reference_scope"] = reference_scope(
            payload["source_sections"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )
        payload["source_issues"] = []
        self.assert_rejected(payload, "parent link")

    def test_same_role_and_table_key_do_not_replace_the_exact_original_anchor(self):
        _, payload = self.run_binding(["73", "28"], mutate_page=continued_page)
        section = continuation_section(payload)
        anchor = section["source"]["header_scope"]["anchor_scope"]
        for source in anchor["context_sources"]:
            for token in source["tokens"]:
                if token["text"] == "Compounds":
                    token["text"] = "Examples"
            source["text"] = cell_text(source["tokens"], source["bbox"])
        rewrite_continuation(payload, section)
        self.assert_rejected(payload, "registered original anchor")

    def test_same_page_shared_original_context_cannot_be_rewritten_independently(self):
        _, payload = self.run_binding(["73", "28"], mutate_page=same_page_part)
        section = continuation_section(payload)
        for chunk in section["source"]["header_scope"]["leading_context"]:
            for source in chunk["sources"]:
                for token in source["tokens"]:
                    if token["text"] == "73":
                        token["text"] = "74"
                source["text"] = cell_text(source["tokens"], source["bbox"])
        rewrite_continuation(payload, section)
        self.assert_rejected(payload, "projection differs")
