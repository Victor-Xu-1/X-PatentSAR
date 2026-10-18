"""Actual source/binder controls for a catalogue's repeated preparation drawing."""

import copy
import json
import unittest
from pathlib import Path

import fitz
from recognition_source_support import observation

from patent_sar_extractor.application.binding_policy import _binding_acceptance_errors
from patent_sar_extractor.application.smiles_policy import _smiles_acceptance_errors
from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.binding_geometry import _process_structure
from patent_sar_extractor.core.caption_role_semantics import catalog_title_namespace
from patent_sar_extractor.core.catalog_reader import (
    CatalogValidationError,
    read_catalog_entries,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_declaration_index import HeadingDeclarationIndex
from patent_sar_extractor.core.heading_evidence import (
    heading_structure_evidence,
    original_heading_lines,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.smiles_artifact import build_smiles_artifact
from tests import test_heading_label_roles as label_controls


class HeadingReprintSourceTests(unittest.TestCase):
    def original(
        self, *, heading="Compound 17: Preparation", catalog_title="Table 47. Compounds"
    ):
        control = label_controls.HeadingLabelRoleTests()
        control.setUp()
        self.addCleanup(control.doCleanups)
        source, _, _ = control.run_binding(catalog_title=catalog_title)
        root = control.root / "repeated-input"
        root.mkdir()
        pdf = root / "repeated-original.pdf"
        image = root / "repeated-structure.png"
        bounds = [70, 100, 200, 220]
        with fitz.open(source) as document:
            page = document.new_page(width=500, height=600)
            page.insert_text((40, 60), heading, fontsize=11)
            page.draw_polyline(
                [
                    (90, 130),
                    (130, 110),
                    (170, 130),
                    (170, 180),
                    (130, 205),
                    (90, 180),
                    (90, 130),
                ],
                color=(0, 0, 0),
                width=1.5,
            )
            page.insert_text((40, 300), "Step 1: Preparation", fontsize=11)
            page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(bounds)).save(
                image
            )
            document.save(pdf)
        metadata = root / "structures.json"
        inputs = json.loads((control.root / "structures.json").read_text())
        inputs["structures"].append(
            {
                "structure_id": "S117",
                "structure_index": 117,
                "page_no": 2,
                "bbox_pdf": bounds,
                "image_path": str(image),
            }
        )
        metadata.write_text(json.dumps(inputs))
        result = bind(
            str(pdf), {"bind_workers": 1}, str(root / "repeated"), str(metadata)
        )
        return result, load_json(result["output_files"]["json"], {})

    def test_proved_preparation_depiction_is_retained_for_chemical_reprint_checks(self):
        result, payload = self.original()
        self.assertEqual(result["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        owners = {r["cpd"]: r for r in payload["compound_catalog"]["entries"]}
        self.assertEqual(set(owners), {"Compound 17", "Compound 18", "Compound 19"})
        self.assertEqual(owners["Compound 17"]["structure_id"], "S17")
        self.assertEqual(
            [r["structure_id"] for r in owners["Compound 17"]["additional_sources"]],
            ["S117"],
        )
        plan = recognition_inputs(payload)
        self.assertEqual([r["structure_id"] for r in plan.reprints], ["S117"])
        self.assertEqual(
            len(plan.work_items),
            4,
            "Source association is not permission to omit a chemical check",
        )

    def test_a_novel_declared_compound_remains_a_primary_source(self):
        _, payload = self.original(heading="Compound 97B: Preparation")
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        plan = recognition_inputs(payload)
        self.assertEqual(
            {r["cpd"] for r in plan.formal},
            {"Compound 17", "Compound 18", "Compound 19", "Compound 97B"},
        )
        self.assertEqual(plan.reprints, [])

    def test_example_and_compound_namespaces_are_not_aliased_by_equal_numbers(self):
        _, payload = self.original(heading="Example 17: Preparation")
        self.assertTrue(payload["source_issues"])
        self.assertTrue(coverage_errors(payload))
        owner = next(r for r in payload["final_bindings"] if r["cpd"] == "Compound 17")
        self.assertEqual(owner["structure_id"], "S17")
        self.assertEqual(owner["additional_sources"], [])
        self.assertTrue(
            any(
                r["reason"] == "unresolved_heading_reference"
                for r in payload["source_issues"]
            )
        )

    def test_namespace_requires_a_literal_unambiguous_original_catalogue_title(self):
        cases = {
            "Table 7. Compounds": "compound",
            "Table7.SelectedCompounds": "compound",
            "Table 9. Examples": "example",
            "Table 8. Structures": "",
            "Table 8. Target products": "",
            "Table 8. Compounds and examples": "",
            "Table 8. Not compounds": "",
            "Table 8. Intermediate compounds": "",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(catalog_title_namespace(text), expected)

    def test_unknown_or_mixed_catalogues_do_not_grant_heading_aliases(
        self,
    ):
        for title in (
            "Table 47. Structures",
            "Table47.CompoundsAndExamples",
        ):
            with self.subTest(title=title):
                _, payload = self.original(catalog_title=title)
                self.assertTrue(coverage_errors(payload))
                self.assertTrue(
                    any(
                        r["reason"] == "unresolved_heading_reference"
                        for r in payload["source_issues"]
                    )
                )
                owner = next(
                    r for r in payload["final_bindings"] if r["cpd"] == "Compound 17"
                )
                self.assertEqual(owner["additional_sources"], [])

    def test_a_selected_catalogue_can_remain_the_primary_when_no_other_catalogue_owns_it(
        self,
    ):
        _, payload = self.original(catalog_title="Table47.SelectedCompounds")
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        plan = recognition_inputs(payload)
        self.assertEqual(len(plan.formal), 3)
        self.assertEqual([r["structure_id"] for r in plan.reprints], ["S117"])

    def test_a_known_cell_prefix_conflict_cannot_be_overridden_by_its_table_title(self):
        _, payload = self.original(
            heading="Example 17: Preparation", catalog_title="Table 47. Examples"
        )
        self.assertTrue(coverage_errors(payload))
        self.assertTrue(
            any(
                r["reason"] == "unresolved_heading_reference"
                for r in payload["source_issues"]
            )
        )

    def test_an_opaque_namespace_flag_cannot_replace_original_source_vocabulary(self):
        _, payload = self.original()
        entry = next(
            r
            for r in payload["compound_catalog"]["entries"]
            if r["cpd"] == "Compound 17"
        )
        repeated = entry["additional_sources"][0]
        repeated["source_namespace"] = "example"
        self.assertEqual(
            read_catalog_entries(payload)[0][0]["structure_id"],
            "S17",
            "Only original qualified vocabulary supplies the namespace",
        )

    def test_saved_heading_cannot_be_promoted_over_its_original_catalogue(self):
        _, payload = self.original()
        entry = next(
            r
            for r in payload["compound_catalog"]["entries"]
            if r["cpd"] == "Compound 17"
        )
        original = {k: v for k, v in entry.items() if k != "additional_sources"}
        repeated = entry["additional_sources"][0]
        payload["compound_catalog"]["entries"] = [
            {**repeated, "additional_sources": [original]} if r is entry else r
            for r in payload["compound_catalog"]["entries"]
        ]
        with self.assertRaisesRegex(CatalogValidationError, "claim"):
            read_catalog_entries(payload)

    def test_retaining_the_id_cannot_hide_an_omitted_heading_occurrence(self):
        _, payload = self.original()
        for entry in payload["compound_catalog"]["entries"]:
            entry["additional_sources"] = []
        payload["source_issues"] = []
        self.assertTrue(coverage_errors(payload))
        self.assertTrue(_binding_acceptance_errors(payload))

    def test_foreign_or_changed_heading_evidence_is_not_a_reprint(self):
        _, original = self.original()
        for mutation in ("document", "crop", "scope"):
            payload = copy.deepcopy(original)
            entry = next(
                r
                for r in payload["compound_catalog"]["entries"]
                if r["cpd"] == "Compound 17"
            )
            repeated = entry["additional_sources"][0]
            if mutation == "document":
                repeated["source_pdf_sha256"] = "f" * 64
            elif mutation == "crop":
                repeated["original_heading_structure_evidence"]["crop_sha256"] = (
                    "f" * 64
                )
            else:
                repeated["original_heading_structure_evidence"]["declaration_scope"][
                    "pages"
                ].pop()
            with (
                self.subTest(mutation=mutation),
                self.assertRaises(CatalogValidationError),
            ):
                read_catalog_entries(payload)

    def test_formal_recognition_cannot_redirect_only_the_heading_proof(self):
        _, payload = self.original()
        for index, row in enumerate(payload["final_bindings"]):
            if row["cpd"] != "Compound 19":
                continue
            row = copy.deepcopy(row)
            row["original_heading_structure_evidence"]["declaration_scope"][
                "document_page_count"
            ] += 1
            payload["final_bindings"][index] = row
        with self.assertRaisesRegex(ValueError, "source"):
            recognition_inputs(payload)

    def test_heading_depictions_use_the_existing_complete_chemical_graph_gate(self):
        _, payload = self.original()
        plan = recognition_inputs(payload)
        for primary, repeated, consistent in (
            ("C1CCCCC1", "C1CCCCC1", True),
            ("C1CCCCC1", "C1CCCC1", False),
            ("CCO", "[13CH3]CO", False),
            ("CCN", "CC[NH3+]", False),
            ("C[C@H](F)Cl", "C[C@@H](F)Cl", False),
            ("C[C@H](F)Cl", "CC(F)Cl", False),
            ("CCO.[Na+]", "CCO", False),
        ):
            artifact = build_smiles_artifact(
                [observation(row, primary) for row in plan.formal],
                reprint_records=[observation(row, repeated) for row in plan.reprints],
            )
            with self.subTest(primary=primary, repeated=repeated):
                self.assertEqual(
                    not _smiles_acceptance_errors(artifact, payload), consistent
                )

    def test_clean_primary_graphs_do_not_accept_an_unexecuted_heading_depiction(self):
        _, payload = self.original()
        artifact = build_smiles_artifact(
            [observation(row) for row in payload["final_bindings"]]
        )
        self.assertTrue(_smiles_acceptance_errors(artifact, payload))

    def test_a_biology_experiment_cannot_acquire_compound_role_from_locator_metadata(
        self,
    ):
        result, payload = self.original(heading="Example 17: Biological evaluation")
        root = Path(result["output_files"]["json"]).parent.parent
        proof = next(
            s["heading_observation"]
            for s in payload["source_sections"]
            if s["role"] == "assay_section"
        )
        structures = [
            _process_structure(s)
            for s in json.loads((root / "structures.json").read_text())["structures"]
        ]
        with fitz.open(root / "repeated-original.pdf") as document:
            scope = HeadingDeclarationIndex(
                document,
                structures,
                lambda number: original_heading_lines(document[number - 1]),
                proof["original_pdf_sha256"],
            ).observe(proof)
            box = proof["nomination"]["bbox"]
            block = {
                "cpd": "Compound 17",
                "page_no": 2,
                "bbox": box,
                "y0": box[1],
                "y1": box[3],
                "line_text": "Compound 17: Preparation",
                "heading_observation": proof,
                "declaration_scope": scope,
            }
            by_id = {
                s["id"]: {**s, "source_pdf_sha256": proof["original_pdf_sha256"]}
                for s in structures
            }
            selected, evidence = heading_structure_evidence(
                block, by_id, scope, document=document
            )
        self.assertIsNone(selected)
        self.assertIsNone(evidence)

    def test_saved_metadata_cannot_rewrite_the_qualified_original_heading_text(self):
        _, payload = self.original()
        entry = next(
            r
            for r in payload["compound_catalog"]["entries"]
            if r["cpd"] == "Compound 17"
        )
        repeated = copy.deepcopy(entry["additional_sources"][0])
        repeated["original_heading_evidence"]["line_text"] = (
            "Synthesis of Compound 17: Product"
        )
        repeated["original_heading_structure_evidence"]["heading_text"] = (
            "Synthesis of Compound 17: Product"
        )
        self.assertTrue(annotate_binding_accuracy(repeated)["fail_closed"])


if __name__ == "__main__":
    unittest.main()
