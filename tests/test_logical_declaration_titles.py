"""One original unruled header drives both rows and complete page declarations."""

import copy
import unittest
from unittest.mock import patch

import fitz
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.structure_declaration_scopes import (
    declaration_page_id,
    declaration_scopes,
)
from patent_sar_extractor.core.structure_declarations import observe_declaration_pages
from patent_sar_extractor.core.table_geometry import page_tokens


class LogicalDeclarationTitleTests(LateralStructureControls, unittest.TestCase):
    def original(self, **options):
        _result, payload = self.run_case(ruled=False, nonfinal=True, **options)
        page = next(
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_declaration_page"
        )
        self.assertEqual(page["source"]["version"], 3)
        self.assertEqual(len(page["source"]["logical_columns"]), 2)
        return payload, page

    def test_complete_scan_page_reuses_original_header_without_another_title_read(self):
        payload, page = self.original(raster=True)
        columns = page["source"]["logical_columns"]
        diagrams = [
            {
                "id": d["id"],
                "page_no": 1,
                **dict(zip(("x0", "y0", "x1", "y1"), d["bbox"], strict=True)),
            }
            for d in page["source"]["page_diagrams"]
        ]
        with fitz.open(self.root / "original.pdf") as document:
            tokens = page_tokens(document[0], dpi=200, allow_tesseract=False)
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Do not reread the same title"),
            ):
                sections, withheld = observe_declaration_pages(
                    document,
                    diagrams,
                    [0],
                    {0: "Compound No. Structure"},
                    lambda _p: tokens,
                    grids_for_page=lambda _p: [],
                    column_sections=columns,
                )
        self.assertEqual(
            [s["role"] for s in declaration_scopes(sections[0]["source"])],
            ["compound", "nonfinal"],
        )
        self.assertEqual(withheld, {"C1-901A", "C1-I-003B"})
        self.assertEqual(
            reference_issues(payload, payload["compound_catalog"]["entries"]), []
        )

    def test_rehashed_removal_reordering_or_version_downgrade_cannot_hide_owners(self):
        payload, _page = self.original()
        for operation in ("remove", "reorder", "downgrade"):
            saved = copy.deepcopy(payload)
            page = next(
                s
                for s in saved["source_sections"]
                if s["role"] == "structure_declaration_page"
            )
            source = page["source"]
            if operation == "remove":
                source["logical_columns"].pop()
            elif operation == "reorder":
                source["logical_columns"].reverse()
            else:
                source.pop("logical_columns")
                source["version"] = 2
            page["region_id"] = declaration_page_id(source)
            saved["source_reference_scope"] = reference_scope(saved["source_sections"])
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                reference_issues(saved, saved["compound_catalog"]["entries"])

    def test_foreign_source_page_identity_duplicate_or_changed_diagrams_refuse(self):
        _payload, page = self.original()
        for field, value in (("original_pdf_sha256", "b" * 64), ("page_no", 2)):
            changed = copy.deepcopy(page["source"])
            section = changed["logical_columns"][0]
            section["source"]["header_scope"][field] = value
            section["region_id"] = proof_id(section["source"])
            with self.subTest(field=field), self.assertRaises(ValueError):
                declaration_page_id(changed)
        changed = copy.deepcopy(page["source"])
        changed["logical_columns"].append(copy.deepcopy(changed["logical_columns"][0]))
        with self.assertRaises(ValueError):
            declaration_page_id(changed)
        changed = copy.deepcopy(page["source"])
        changed["page_diagrams"].pop()
        with self.assertRaises(ValueError):
            declaration_page_id(changed)

    def test_historical_representation_remains_readable_without_current_admission(self):
        payload, page = self.original()
        page["source"].pop("logical_columns")
        page["source"]["version"] = 2
        page["region_id"] = declaration_page_id(page["source"])
        payload["source_reference_scope"] = reference_scope(payload["source_sections"])
        issues = reference_issues(
            payload, payload["compound_catalog"]["entries"], required=False
        )
        self.assertIsInstance(issues, list)
        with self.assertRaises(ValueError):
            reference_issues(payload, payload["compound_catalog"]["entries"])

    def test_header_word_roles_cannot_replace_an_unknown_original_title(self):
        def unknown_title(document, _records):
            page = document[0]
            page.add_redact_annot(fitz.Rect(350, 25, 650, 58))
            page.apply_redactions()
            page.insert_text((360, 45), "Table B8. Observations", fontsize=9)

        payload, page = self.original(mutate_document=unknown_title)
        scopes = declaration_scopes(page["source"])
        self.assertEqual({s["role"] for s in scopes}, {"compound", "unknown"})
        self.assertTrue(all(not s["unproved_title"] for s in scopes))
        self.assertEqual(len(payload["compound_catalog"]["entries"]), 4)


if __name__ == "__main__":
    unittest.main()
