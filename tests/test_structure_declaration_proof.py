"""Declared source completeness survives saved flags and result count edits."""

import json
import unittest

from test_structure_declarations import independent_caption_page
from test_unruled_continuation import continued_page
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


class StructureDeclarationProofTests(UnruledStructureControls, unittest.TestCase):
    def test_clearing_reported_issues_cannot_erase_an_unanchored_source(self):
        _, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: continued_page(
                page, structures, caption="Table 13. Continued"
            ),
        )
        payload["source_issues"] = []
        self.assertTrue(
            reference_issues(payload, payload["compound_catalog"]["entries"])
        )
        self.assertTrue(coverage_errors(payload))

    def test_omitting_an_independently_captioned_diagram_is_replayed_as_a_gap(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=independent_caption_page
        )
        for rows in (payload["compound_catalog"]["entries"], payload["final_bindings"]):
            rows[:] = [row for row in rows if row["structure_id"] != "CAP1"]
        payload["source_issues"] = []
        payload["compound_catalog"]["numbered_compounds"] = 3
        payload["compound_catalog"]["source_observations"] = 3
        payload["final_bindings_count"] = 3
        self.assertTrue(
            reference_issues(payload, payload["compound_catalog"]["entries"])
        )
        self.assertTrue(coverage_errors(payload))

    def test_serialized_independent_caption_sources_remain_usable(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=independent_caption_page
        )
        payload = json.loads(json.dumps(payload))
        self.assertEqual(len(read_catalog_entries(payload)[0]), 4)
        self.assertEqual(
            len(read_compound_catalog(payload, payload["final_bindings"])[0]), 4
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_deleting_a_declared_page_without_its_scope_is_rejected(self):
        _, payload = self.run_binding(
            ["73", "28"], mutate_page=independent_caption_page
        )
        payload["source_sections"] = [
            s
            for s in payload["source_sections"]
            if s.get("role") != "structure_declaration_page"
        ]
        payload["source_issues"] = []
        with self.assertRaises(ValueError):
            reference_issues(payload, payload["compound_catalog"]["entries"])
