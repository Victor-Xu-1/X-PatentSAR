"""Whole original declaration spans, not the heading page's nearest diagram."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.application.binding_policy import _binding_acceptance_errors
from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.binding_source_headings import (
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.heading_declaration_scope import declaration_candidates
from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.ocsr.run_smiles import validate_strict_binding_input
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.files import SafeFiles


class HeadingDocumentSpanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-heading-span-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.document = fitz.open()
        self.addCleanup(self.document.close)

    def page(self):
        return self.document.new_page(width=500, height=600)

    def drawing(self, page_no, identity, *, top=100):
        page = self.document[page_no - 1]
        page.draw_polyline(
            [
                (120, top + 30),
                (165, top),
                (210, top + 30),
                (210, top + 75),
                (165, top + 100),
                (120, top + 75),
                (120, top + 30),
            ],
            color=(0, 0, 0),
            width=1.5,
        )
        bounds = [105, top - 10, 230, top + 115]
        image = self.root / f"{identity}.png"
        page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(bounds)).save(image)
        return dict(
            zip(("x0", "y0", "x1", "y1"), bounds),
            id=identity,
            idx=int(identity[1:]),
            page_no=page_no,
            image_path=str(image),
        )

    def select(self, structures, *, all_structures=None):
        self.sections = []
        blocks = observed_heading_blocks(
            self.document,
            list(range(len(self.document))),
            {},
            source_sections=self.sections,
        )
        return select_heading_bindings(
            self.document,
            structures,
            blocks,
            {},
            str(self.root / "bindings"),
            {},
            all_structures=all_structures,
            source_sections=self.sections,
        )

    def test_original_heading_may_own_one_diagram_on_the_next_page(self):
        self.page().insert_text((45, 540), "Exemplary Compound 007B", fontsize=12)
        self.page().insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        structure = self.drawing(2, "S1")
        bindings, issues = self.select([structure])
        self.assertEqual(issues, [])
        self.assertEqual(
            [(b["cpd"], b["page_no"]) for b in bindings], [("Compound 007B", 2)]
        )
        self.assertEqual(
            annotate_binding_accuracy(bindings[0])["accuracy_status"], "confirmed"
        )

    def test_a_scheme_continued_on_the_next_page_is_not_a_unique_standalone(self):
        self.page().insert_text((45, 60), "Compound 31", fontsize=12)
        first = self.drawing(1, "S1")
        self.page().insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        second = self.drawing(2, "S2")
        bindings, issues = self.select([first, second])
        self.assertEqual(
            bindings, [], "The first page's sole reagent must not become the product"
        )
        self.assertEqual([issue["cpd"] for issue in issues], ["Compound 31"])

    def test_empty_continuation_pages_are_not_skipped_from_the_source_span(self):
        self.page().insert_text((45, 540), "Compound Z-008A", fontsize=12)
        self.page()
        self.page().insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        bindings, issues = self.select([self.drawing(3, "S1")])
        self.assertEqual(issues, [])
        self.assertEqual(bindings[0]["page_no"], 3)
        evidence = bindings[0]["original_heading_structure_evidence"]
        self.assertEqual(
            [p["page_no"] for p in evidence["declaration_scope"]["pages"]], [1, 2, 3]
        )

    def test_an_explicit_procedure_stop_prevents_ownership_of_later_diagrams(self):
        self.page().insert_text((45, 60), "Compound 41", fontsize=12)
        self.document[0].insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        first = self.drawing(1, "S1")
        self.page()
        second = self.drawing(2, "S2")
        bindings, issues = self.select([first, second])
        self.assertEqual(issues, [])
        self.assertEqual([b["structure_id"] for b in bindings], ["S1"])

    def test_the_next_heading_owns_its_own_diagram_not_the_prior_page_heading(self):
        self.page().insert_text((45, 540), "Compound 51", fontsize=12)
        self.page().insert_text((45, 60), "Compound 52", fontsize=12)
        self.document[1].insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        bindings, issues = self.select([self.drawing(2, "S1")])
        self.assertEqual([b["cpd"] for b in bindings], ["Compound 52"])
        self.assertEqual([issue["cpd"] for issue in issues], ["Compound 51"])

    def test_a_partial_structure_at_the_procedure_boundary_is_not_silently_ignored(
        self,
    ):
        self.page().insert_text((45, 60), "Compound 61", fontsize=12)
        self.document[0].insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        first = self.drawing(1, "S1")
        crossing = self.drawing(1, "S2", top=250)
        bindings, issues = self.select([first, crossing])
        self.assertEqual(
            bindings, [], "A cut second candidate makes the scope ambiguous"
        )
        self.assertTrue(issues)

    def test_cross_page_scope_cannot_be_shortened_or_reassigned_after_capture(self):
        self.page().insert_text((45, 540), "Compound 71A", fontsize=12)
        self.page().insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        bindings, issues = self.select([self.drawing(2, "S1")])
        self.assertEqual(issues, [])
        baseline = bindings[0]
        packets = []
        for name, value in (("page_no", 1), ("cpd", "Compound 71B")):
            changed = copy.deepcopy(baseline)
            changed[name] = value
            packets.append(changed)
        changed = copy.deepcopy(baseline)
        changed["original_heading_structure_evidence"]["declaration_scope"][
            "pages"
        ].pop(0)
        packets.append(changed)
        for packet in packets:
            with self.subTest(packet=packet.get("page_no")):
                self.assertTrue(annotate_binding_accuracy(packet)["fail_closed"])

    def test_reserved_candidates_still_participate_in_uniqueness(self):
        self.page().insert_text((45, 60), "Compound 81", fontsize=12)
        first = self.drawing(1, "S1")
        self.page().insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        second = self.drawing(2, "S2")
        bindings, issues = self.select([first], all_structures=[first, second])
        self.assertEqual(bindings, [])
        self.assertTrue(issues)
        scope = self.sections[0]["declaration_scope"]
        candidates, complete = declaration_candidates(
            scope, self.sections[0]["heading_observation"]
        )
        self.assertTrue(complete)
        self.assertEqual([s["structure_id"] for s in candidates], ["S1", "S2"])

    def test_parallel_titles_without_original_column_scope_remain_ambiguous(self):
        page = self.page()
        page.insert_text((30, 60), "Compound 91", fontsize=10)
        page.insert_text((300, 60), "Compound 92", fontsize=10)
        bindings, issues = self.select([self.drawing(1, "S1")])
        self.assertEqual(bindings, [])
        self.assertEqual({i["cpd"] for i in issues}, {"Compound 91", "Compound 92"})

    def test_unknown_range_heading_stops_the_prior_source_without_inventing_members(
        self,
    ):
        self.page().insert_text((45, 540), "Compound 101A", fontsize=12)
        self.page().insert_text((45, 60), "Compounds 103 through 109", fontsize=12)
        bindings, issues = self.select([self.drawing(2, "S1")])
        self.assertEqual(bindings, [])
        self.assertTrue(issues)
        self.assertFalse(any(i.get("cpd") == "Compound 104" for i in issues))

    def test_overlong_source_span_is_an_explicit_refusal_not_truncated_uniqueness(self):
        self.page().insert_text((45, 60), "Compound 111A", fontsize=12)
        first = self.drawing(1, "S1")
        for _ in range(64):
            self.page()
        bindings, issues = self.select([first])
        self.assertEqual(bindings, [])
        self.assertTrue(issues)
        self.assertEqual(
            self.sections[0]["declaration_scope"]["stop"]["kind"], "page_limit"
        )

    def test_saved_scope_requires_original_types_geometry_and_every_candidate(self):
        self.page().insert_text((45, 540), "Compound 121A", fontsize=12)
        self.page().insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        bindings, issues = self.select([self.drawing(2, "S1")])
        self.assertEqual(issues, [])
        baseline = bindings[0]
        for mutation in (
            "omit_candidate",
            "change_source",
            "bool_page",
            "change_stop",
            "duplicate",
            "skip_page",
        ):
            changed = copy.deepcopy(baseline)
            scope = changed["original_heading_structure_evidence"]["declaration_scope"]
            if mutation == "omit_candidate":
                scope["pages"][1]["structures"] = []
            elif mutation == "change_source":
                scope["original_pdf_sha256"] = "0" * 64
            elif mutation == "bool_page":
                scope["pages"][0]["page_no"] = True
            elif mutation == "change_stop":
                scope["stop"]["y"] += 1
            elif mutation == "duplicate":
                scope["pages"][1]["structures"] *= 2
            else:
                scope["pages"][1]["page_no"] = 3
            with self.subTest(mutation=mutation):
                self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_actual_binder_writer_and_saved_inventory_share_the_cross_page_scope(self):
        self.page().insert_text((45, 540), "Compound 131B", fontsize=12)
        self.page().insert_text((45, 300), "Step 1: Preparation", fontsize=11)
        drawing = self.drawing(2, "S1")
        pdf, metadata = self.root / "source.pdf", self.root / "structures.json"
        self.document.save(pdf)
        metadata.write_text(
            json.dumps(
                {
                    "patent_number": "CONTROLLED-SPAN",
                    "structures": [
                        {
                            "structure_id": drawing["id"],
                            "structure_index": drawing["idx"],
                            "page_no": 2,
                            "bbox_pdf": [drawing[k] for k in ("x0", "y0", "x1", "y1")],
                            "image_path": drawing["image_path"],
                        }
                    ],
                }
            )
        )
        result = bind(
            str(pdf), {"bind_workers": 1}, str(self.root / "bound"), str(metadata)
        )
        self.assertEqual(result["source_issues"], [])
        self.assertEqual(
            [(r["cpd"], r["page_no"]) for r in result["bindings"]],
            [("Compound 131B", 2)],
        )
        saved = load_json(self.root / "bound" / "bindings.json", {})
        self.assertEqual(reference_issues(saved, saved["final_bindings"]), [])
        self.assertEqual(_binding_acceptance_errors(saved), [])
        self.assertEqual(
            validate_strict_binding_input(
                str(self.root / "bound" / "bindings.json"), saved["final_bindings"]
            ),
            [],
        )
        self.assertEqual(recognition_inputs(saved).formal[0]["page_no"], 2)
        web = SafeFiles(self.root / "bound").json("bindings.json", optional=False)
        entries, _ = read_compound_catalog(web, web["final_bindings"])
        self.assertEqual(entries[0]["page_no"], 2)
        changed = copy.deepcopy(saved)
        section = next(
            s for s in changed["source_sections"] if "declaration_scope" in s
        )
        section.pop("declaration_scope")
        changed["source_reference_scope"] = reference_scope(changed["source_sections"])
        self.assertTrue(
            reference_issues(changed, changed["final_bindings"]),
            "An ID elsewhere cannot discharge the missing exact source scope",
        )

    def test_legacy_page_only_proof_cannot_replace_the_current_scope(self):
        self.page().insert_text((45, 60), "Compound 141B", fontsize=12)
        bindings, issues = self.select([self.drawing(1, "S1")])
        self.assertEqual(issues, [])
        for version in (2, True, 3.0, "3"):
            changed = copy.deepcopy(bindings[0])
            changed["original_heading_structure_evidence"]["version"] = version
            with self.subTest(version=version):
                self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_coarse_footer_geometry_is_bounded_by_the_original_page(self):
        page = self.page()
        lines = original_heading_lines(
            page, [(595, "149"), (600, "outside"), (-1, "outside")]
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["bbox"], [0, 595, 500, 600])
        self.assertEqual(lines[0]["y1"], 600)


if __name__ == "__main__":
    unittest.main()
