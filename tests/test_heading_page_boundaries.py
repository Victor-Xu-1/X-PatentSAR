"""A later page's own proved foreign catalogue must not cut another declaration."""

import copy
import unittest
from unittest.mock import patch

import fitz
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_declaration_scope import declaration_candidates
from patent_sar_extractor.core.heading_evidence import valid_heading_binding_evidence
from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


class HeadingPageBoundaryTests(LateralStructureControls, unittest.TestCase):
    def source(
        self,
        *,
        label="87B",
        foreign_left=40,
        known=True,
        extra=False,
        own_row=False,
        raster=False,
        ruled=True,
    ):
        own_left = 360 if foreign_left == 40 else 40

        def continuation(document, records):
            document[0].insert_text(
                (own_left, 430), f"Compound {label}: Preparation", fontsize=10
            )
            page = document.new_page(width=660, height=720)
            page.insert_text(
                (foreign_left, 45),
                "Table 21. Compounds" if known else "Table 21. Unspecified data",
                fontsize=9,
            )
            page.insert_text(
                (foreign_left + 5, 80),
                "Compound No." if known else "Measurement",
                fontsize=8,
            )
            page.insert_text((foreign_left + 110, 80), "Structure", fontsize=8)
            if ruled:
                self.draw_grid(
                    page,
                    [foreign_left, foreign_left + 80, foreign_left + 260],
                    [65, 100, 210, 330],
                )
            for value, centre in zip(
                ((label if own_row else "65A"), "71"), (150, 265), strict=True
            ):
                page.insert_text((foreign_left + 15, centre + 4), value, fontsize=10)
                self.add_drawing(page, records, foreign_left, centre, "TABLE-" + value)
            self.add_drawing(page, records, own_left, 150, "DECLARED-PRODUCT")
            if extra:
                self.add_drawing(page, records, own_left, 265, "UNEXPLAINED-RIVAL")
            page.insert_text(
                (own_left, 375 if extra else 260), "Step 1: Reaction", fontsize=10
            )

        return self.run_case(mutate_document=continuation, raster=raster, ruled=ruled)

    def test_scanned_original_uses_the_same_exclusion_and_original_pixel_contract(self):
        _, payload = self.source(raster=True)
        target = next(
            (
                row
                for row in payload["compound_catalog"]["entries"]
                if row["cpd"] == "Compound 87B"
            ),
            None,
        )
        self.assertIsNotNone(target, payload["source_issues"])
        self.assertEqual(target["structure_id"], "DECLARED-PRODUCT")
        with fitz.open(self.root / "original.pdf") as original:
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Readback must not recognize again"),
            ):
                self.assertEqual(original_heading_source_errors(original, [target]), [])
            original[1].draw_rect(fitz.Rect(45, 38, 55, 45), color=None, fill=(0, 0, 0))
            self.assertTrue(original_heading_source_errors(original, [target]))

    def test_unruled_full_width_region_cannot_invent_an_independent_column(self):
        _, payload = self.source(ruled=False)
        self.assertNotIn(
            "Compound 87B",
            [row["cpd"] for row in payload["compound_catalog"]["entries"]],
        )
        self.assertTrue(coverage_errors(payload))

    def test_saved_later_witnesses_cannot_be_omitted_reordered_or_reused_for_another_page(
        self,
    ):
        for mutation in (
            "omit_page",
            "foreign_page",
            "omit_source",
            "omit_cell",
            "duplicate_cell",
        ):
            with self.subTest(mutation=mutation):
                target = self.target()
                scope = target["original_heading_structure_evidence"][
                    "declaration_scope"
                ]
                witness = scope["later_columns"][0]
                if mutation == "omit_page":
                    scope["later_columns"] = []
                elif mutation == "foreign_page":
                    witness["page_no"] = 1
                elif mutation == "omit_source":
                    witness["sources"] = []
                elif mutation == "omit_cell":
                    witness["sources"][0]["cells"].pop()
                else:
                    witness["sources"][0]["cells"].append(
                        copy.deepcopy(witness["sources"][0]["cells"][0])
                    )
                target["original_heading_evidence"]["declaration_scope"] = scope
                self.assertFalse(valid_heading_binding_evidence(target))

    def test_historical_heading_and_declaration_versions_are_not_promoted(self):
        for mutation in ("heading", "scope"):
            with self.subTest(mutation=mutation):
                target = self.target()
                proof = target["original_heading_structure_evidence"]
                if mutation == "heading":
                    proof["version"] = 5
                else:
                    scope = proof["declaration_scope"]
                    scope["version"] = 2
                    scope.pop("later_columns")
                    target["original_heading_evidence"]["declaration_scope"] = scope
                self.assertFalse(valid_heading_binding_evidence(target))

    def test_saved_title_pixels_cannot_be_substituted_after_serialization(self):
        target = self.target()
        scope = target["original_heading_structure_evidence"]["declaration_scope"]
        frames = scope["later_columns"][0]["sources"][0]["caption_frames"]
        frames[0]["rendered_frames"][0]["pixel_sha256"] = "0" * 64
        target["original_heading_evidence"]["declaration_scope"] = scope
        self.assertTrue(valid_heading_binding_evidence(target))
        with fitz.open(self.root / "original.pdf") as original:
            self.assertTrue(original_heading_source_errors(original, [target]))

    def test_later_page_catalogue_has_its_own_original_boundary_not_a_page_split(self):
        for label, left in (("87B", 40), ("I-009C", 360)):
            with self.subTest(label=label, foreign_left=left):
                result, payload = self.source(label=label, foreign_left=left)
                entries = result["compound_catalog"]["entries"]
                target = next(
                    (row for row in entries if row["cpd"] == "Compound " + label), None
                )
                self.assertIsNotNone(target, payload["source_issues"])
                self.assertEqual(target["structure_id"], "DECLARED-PRODUCT")
                proof = target["original_heading_structure_evidence"]
                scope = proof["declaration_scope"]
                candidates, complete = declaration_candidates(
                    scope, proof["heading_source"]
                )
                self.assertTrue(complete)
                self.assertEqual(
                    [row["structure_id"] for row in candidates], ["DECLARED-PRODUCT"]
                )
                self.assertEqual(len(scope["pages"]), 2)
                self.assertEqual(scope["stop"]["kind"], "source_boundary")
                self.assertEqual(scope["stop"]["page_no"], 2)
                self.assertEqual(coverage_errors(payload), [])
                with fitz.open(self.root / "original.pdf") as original:
                    self.assertEqual(
                        original_heading_source_errors(original, [target]), []
                    )
                saved, _ = read_compound_catalog(payload, entries)
                self.assertIn("Compound " + label, [row["cpd"] for row in saved])

    def test_unknown_later_table_roles_cannot_create_an_accepted_singleton(self):
        _, payload = self.source(known=False)
        self.assertNotIn(
            "Compound 87B", [r["cpd"] for r in payload["compound_catalog"]["entries"]]
        )
        self.assertTrue(coverage_errors(payload))

    def target(self):
        _, payload = self.source()
        return copy.deepcopy(
            next(
                row
                for row in payload["compound_catalog"]["entries"]
                if row["cpd"] == "Compound 87B"
            )
        )

    def test_rehashed_native_cell_source_cannot_replace_actual_original_text(self):
        target = self.target()
        scope = target["original_heading_structure_evidence"]["declaration_scope"]
        witness = scope["later_columns"][0]["sources"][0]

        def replace_text(value):
            if isinstance(value, dict):
                for key, part in value.items():
                    if key in {"text", "value"} and isinstance(part, str):
                        value[key] = part.replace("65A", "66A")
                    else:
                        replace_text(part)
            elif isinstance(value, list):
                for part in value:
                    replace_text(part)

        replace_text(witness)
        witness["section"]["region_id"] = proof_id(witness["section"]["source"])
        target["original_heading_evidence"]["declaration_scope"] = scope
        self.assertTrue(valid_heading_binding_evidence(target))
        with fitz.open(self.root / "original.pdf") as original:
            self.assertTrue(original_heading_source_errors(original, [target]))

    def test_a_saved_page_inventory_cannot_delete_an_original_boundary(self):
        target = self.target()
        scope = target["original_heading_structure_evidence"]["declaration_scope"]
        scope["pages"][1]["lines"] = [
            line
            for line in scope["pages"][1]["lines"]
            if not line["text"].startswith("Step 1")
        ]
        scope["stop"] = {"kind": "document_end", "page_no": 2, "y": 720.0}
        target["original_heading_evidence"]["declaration_scope"] = scope
        self.assertTrue(valid_heading_binding_evidence(target))
        with fitz.open(self.root / "original.pdf") as original:
            self.assertTrue(original_heading_source_errors(original, [target]))

    def test_an_unowned_rival_outside_the_foreign_table_remains_ambiguous(self):
        _, payload = self.source(extra=True)
        self.assertNotIn(
            "Compound 87B", [r["cpd"] for r in payload["compound_catalog"]["entries"]]
        )
        self.assertTrue(coverage_errors(payload))

    def test_own_printed_identifier_in_a_table_cannot_be_excluded_as_foreign(self):
        _, payload = self.source(own_row=True)
        self.assertFalse(
            any(
                row["cpd"] == "Compound 87B"
                and row["structure_id"] == "DECLARED-PRODUCT"
                for row in payload["compound_catalog"]["entries"]
            )
        )
        self.assertTrue(coverage_errors(payload))
