"""Current continuation declarations join the registered original source, not OCR votes."""

import copy
import unittest

import test_lateral_column_continuation as continuation_controls
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.structure_declaration_scopes import (
    declaration_page_id,
    declaration_scopes,
)


class DeclarationContinuationSourceTests(LateralStructureControls, unittest.TestCase):
    continued_tables = (
        continuation_controls.LateralColumnContinuationTests.continued_tables
    )

    def original(self):
        _result, payload = self.run_case(mutate_document=self.continued_tables)
        page = next(
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_declaration_page" and s["page_no"] == 2
        )
        self.assertEqual(page["source"]["version"], 4)
        self.assertEqual(len(page["source"]["continued_columns"]), 2)
        return payload, page

    def test_headerless_page_reuses_complete_column_proof_without_rewriting_raw_titles(
        self,
    ):
        payload, page = self.original()
        scopes = declaration_scopes(page["source"])
        self.assertEqual(coverage_errors(payload), [])
        self.assertEqual([s["role"] for s in scopes], ["compound", "compound"])
        self.assertTrue(all(s.get("continuation_source_region") for s in scopes))
        self.assertTrue(all(not s["unproved_title"] for s in scopes))
        self.assertEqual(
            [s["role"] for s in page["source"]["catalogue_scopes"]],
            ["unknown", "unknown"],
        )

    def test_rehashed_omission_or_version_downgrade_cannot_waive_a_continuation(self):
        payload, _page = self.original()
        for operation in ("remove", "downgrade"):
            saved = copy.deepcopy(payload)
            page = next(
                s
                for s in saved["source_sections"]
                if s["role"] == "structure_declaration_page" and s["page_no"] == 2
            )
            if operation == "remove":
                page["source"]["continued_columns"].pop()
            else:
                page["source"].pop("continued_columns")
                page["source"].pop("logical_columns")
                page["source"]["version"] = 2
            page["region_id"] = declaration_page_id(page["source"])
            saved["source_reference_scope"] = reference_scope(saved["source_sections"])
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                reference_issues(saved, saved["compound_catalog"]["entries"])

    def test_changed_foreign_column_source_or_original_grid_cannot_supply_a_role(self):
        _payload, page = self.original()
        for operation in ("foreign", "grid", "duplicate"):
            source = copy.deepcopy(page["source"])
            column = source["continued_columns"][0]
            if operation == "foreign":
                column["source"]["header_scope"]["original_pdf_sha256"] = "f" * 64
                column["region_id"] = proof_id(column["source"])
            elif operation == "grid":
                source["page_grids"].pop()
            else:
                source["continued_columns"].append(copy.deepcopy(column))
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                declaration_page_id(source)

    def test_unowned_original_prefix_never_becomes_an_empty_continuation(self):
        def changed(document, records):
            self.continued_tables(document, records)
            document[1].insert_text(
                (40, 40), "A different experiment was performed.", fontsize=9
            )

        _result, payload = self.run_case(mutate_document=changed)
        page = next(
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_declaration_page" and s["page_no"] == 2
        )
        self.assertTrue(coverage_errors(payload))
        scopes = declaration_scopes(page["source"])
        self.assertFalse(any(s.get("continuation_source_region") for s in scopes))


if __name__ == "__main__":
    unittest.main()
