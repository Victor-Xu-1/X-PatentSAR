"""Complete original group declarations, not inferred diagram order or IDs."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_source_headings import (
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration


class OriginalHeadingInventoryTests(unittest.TestCase):
    @staticmethod
    def document(title):
        document = fitz.open()
        page = document.new_page(width=700, height=600)
        page.insert_text((40, 65), title, fontsize=11)
        return document

    def test_all_literal_plural_heading_members_are_inventoried(self):
        for title, identifiers in (
            ("Exemplary Compounds Z-007B and Z-007A", ["Z-007B", "Z-007A"]),
            ("Compounds 008A, 009C, and 004D", ["008A", "009C", "004D"]),
            ("Synthesis of Compounds 74 and 103", ["74", "103"]),
            ("Examples 12A and 19B: Preparation", ["12A", "19B"]),
        ):
            with self.subTest(title=title), self.document(title) as document:
                sections = []
                blocks = observed_heading_blocks(
                    document, [0], {}, source_sections=sections
                )
                self.assertEqual(
                    [block["cpd"] for block in blocks],
                    [f"Compound {identifier}" for identifier in identifiers],
                    "A plural declaration must not disappear from completeness",
                )
                self.assertTrue(sections, "Retain the complete original declaration")
                self.assertTrue(all(block["line_text"] == title for block in blocks))

    def test_missing_group_members_are_issues_not_an_empty_success(self):
        with self.document("Compounds Q-72A and Q-72C") as document:
            blocks = observed_heading_blocks(document, [0], {})
            with tempfile.TemporaryDirectory(
                prefix="patentsar-heading-inventory-"
            ) as out:
                bindings, issues = select_heading_bindings(
                    document, [], blocks, {}, out, {}
                )
        self.assertEqual(bindings, [])
        self.assertEqual(
            {issue["cpd"] for issue in issues}, {"Compound Q-72A", "Compound Q-72C"}
        )

    def test_no_range_expansion_prose_or_assay_numbers_become_compounds(self):
        for title in (
            "For Compounds 72 and 73, the solvent was removed.",
            "Compounds 72 and 73 were evaluated in a binding assay.",
            "Examples 71 and 86: Biological evaluation",
            "Example 7 and Example 9",
            "Compounds 2 through 8",
        ):
            with self.subTest(title=title), self.document(title) as document:
                self.assertEqual(observed_heading_blocks(document, [0], {}), [])

    def observed(self, title="Compounds Q-72A and Q-72C"):
        with self.document(title) as document:
            sections = []
            observed_heading_blocks(document, [0], {}, source_sections=sections)
        return json.loads(
            json.dumps(
                {
                    "source_sections": sections,
                    "source_reference_scope": reference_scope(sections),
                }
            )
        )

    def test_saved_source_replays_every_member_without_id_only_exemptions(self):
        payload = self.observed()
        payload["source_issues"] = []
        self.assertEqual(
            {
                row["cpd"]
                for row in reference_issues(payload, [{"cpd": "Compound Q-72A"}])
            },
            {"Compound Q-72A", "Compound Q-72C"},
        )
        self.assertEqual(
            {
                row["cpd"]
                for row in reference_issues(
                    payload, [{"cpd": "Compound Q-72A"}, {"cpd": "Compound Q-72C"}]
                )
            },
            {"Compound Q-72A", "Compound Q-72C"},
            "Matching IDs are not proof of ownership of either original occurrence",
        )

    def test_removed_changed_or_downgraded_declarations_are_not_a_success(self):
        baseline = self.observed()
        omitted = copy.deepcopy(baseline)
        omitted["source_sections"] = []
        shortened = copy.deepcopy(baseline)
        shortened["source_sections"][0]["identifiers"] = ["Q-72A"]
        stripped = copy.deepcopy(baseline)
        stripped["source_sections"][0].pop("heading_observation")
        downgraded = copy.deepcopy(baseline)
        downgraded["source_reference_scope"].update(version=2)
        downgraded["source_reference_scope"].pop("heading_ids")
        for candidate in (omitted, shortened, stripped, downgraded):
            with (
                self.subTest(candidate=candidate["source_reference_scope"]["version"]),
                self.assertRaises(ValueError),
            ):
                reference_issues(candidate, [{"cpd": "Compound Q-72A"}])

    def test_duplicate_declarations_remain_unproved_and_overflow_is_explicit(self):
        payload = self.observed("Compounds 17 and 17")
        self.assertEqual(payload["source_sections"][0]["status"], "unresolved")
        self.assertTrue(reference_issues(payload, [{"cpd": "Compound 17"}]))
        from patent_sar_extractor.core.source_section_roles import section_heading

        with self.assertRaisesRegex(ValueError, "member bound"):
            section_heading(
                "Compounds " + ", ".join(str(index) for index in range(1, 34))
            )

    def test_declared_experiments_and_intermediates_are_not_terminal_members(self):
        for title in (
            "Examples 71 and 86: Biological evaluation",
            "Intermediates R-7A and R-7B",
        ):
            with self.subTest(title=title):
                payload = self.observed(title)
                self.assertTrue(payload["source_sections"])
                self.assertEqual(reference_issues(payload, []), [])

    def test_native_headings_never_initialize_ocr_and_reject_source_tampering(self):
        with patch(
            "patent_sar_extractor.core.heading_observation.get_ocr_engine",
            side_effect=AssertionError("Native source is sufficient"),
        ):
            payload = self.observed()
        section = payload["source_sections"][0]
        self.assertEqual(section["heading_observation"]["observations"], [])
        for field, value in (("page_no", True), ("original_pdf_sha256", "b" * 64)):
            changed = copy.deepcopy(payload)
            changed["source_sections"][0]["heading_observation"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference_issues(changed, [])

    def test_actual_raster_heading_not_its_page_hint_declares_the_members(self):
        title = "Compounds 73 and 74"
        with self.document(title) as original:
            words = original[0].get_text("words")
            bounds = [
                min(w[0] for w in words),
                min(w[1] for w in words),
                max(w[2] for w in words),
                max(w[3] for w in words),
            ]
            pixels = (
                original[0]
                .get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                .tobytes("png")
            )
        with fitz.open() as document:
            page = document.new_page(width=700, height=600)
            page.insert_image(page.rect, stream=pixels)
            page.insert_text((40, 580), "Native footer only", fontsize=8)
            hint = {
                "text": "Compound 795",
                "y0": bounds[1],
                "bbox": bounds,
                "source": "page_ocr",
                "geometry_space": "rendered",
            }
            sections = []
            blocks = observed_heading_blocks(
                document, [0], {}, source_sections=sections, source_line_map={0: [hint]}
            )
        self.assertEqual(
            [block["cpd"] for block in blocks],
            ["Compound 73", "Compound 74"],
            [
                (
                    s["status"],
                    [r["raw_text"] for r in s["heading_observation"]["observations"]],
                )
                for s in sections
            ],
        )
        proof = sections[0]["heading_observation"]
        self.assertEqual(proof["nomination"]["text"], "Compound 795")
        self.assertEqual(
            [reading["render_dpi"] for reading in proof["observations"]], [400, 600]
        )
        self.assertEqual(len(proof["rendered_frames"]), 2)
        self.assertEqual(
            proved_heading_declaration(json.loads(json.dumps(proof)))["identifiers"],
            ["73", "74"],
        )

    def test_formal_and_web_recheck_unmapped_members_not_stored_success(self):
        from patent_sar_extractor.core.formal_structure import coverage_errors
        from patent_sar_extractor.web.compound_catalog import read_compound_catalog
        from patent_sar_extractor.web.errors import WebError
        from tests.test_source_led_export import run_fixture

        with tempfile.TemporaryDirectory(
            prefix="patentsar-heading-consumers-"
        ) as temporary:
            root = Path(temporary)
            run_fixture(root)
            payload = json.loads(
                (root / "structure_bindings/bindings.json").read_text()
            )
            payload.update(self.observed("Compounds 42 and 42A and 72C"))
            payload["source_issues"] = []
            self.assertTrue(coverage_errors(payload))
            payload["source_sections"] = []
            with self.assertRaises(ValueError):
                coverage_errors(payload)
            with self.assertRaises(WebError):
                read_compound_catalog(
                    payload, [{"structure_id": "S42"}, {"structure_id": "S42A"}]
                )


if __name__ == "__main__":
    unittest.main()
