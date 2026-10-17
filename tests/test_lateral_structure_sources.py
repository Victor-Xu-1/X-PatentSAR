"""Independent original columns keep their own source and scientific roles."""

import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.core.structure_declaration_scopes import declaration_scopes
from patent_sar_extractor.core.unruled_continuation_titles import qualified_table_key
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


class LateralStructureSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="original-lateral-sources-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_case(
        self,
        *,
        nonfinal=False,
        later_product=False,
        raster=False,
        duplicate=False,
        shared_title=False,
        left_later_centre=510,
        native_conflict=False,
        selected=False,
        selected_novel=False,
    ):
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=self.temporary.name))
        original, records = self.root / "original.pdf", []
        with fitz.open() as document:
            page = document.new_page(width=660, height=720)
            for column, left in enumerate((40, 360)):
                title = (
                    "Table 11. Compounds"
                    if column == 0
                    else (
                        "Table B8. Intermediates" if nonfinal else "Table B8. Compounds"
                    )
                )
                if shared_title:
                    title = "Table 11. Intermediates" if column == 0 else ""
                elif selected and column == 1:
                    title = "Table B8. Selected compounds"
                if title:
                    page.insert_text((left, 45), title, fontsize=9)
                page.insert_text((left + 5, 80), "Compound No.", fontsize=8)
                page.insert_text((left + 110, 80), "Structure", fontsize=8)
                xs = [left, left + 80, left + 260]
                ys = (
                    [65, 100, 210, 380, 600]
                    if later_product and column == 0
                    else [65, 100, 210, 330]
                )
                for x in xs:
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((xs[0], y), (xs[-1], y))
                labels = (
                    ["73", "28"]
                    if column == 0
                    else ["73" if duplicate else "901A", "I-003B"]
                )
                if selected and column == 1:
                    labels = ["73", "I-003B" if selected_novel else "28"]
                centres = [150, 265]
                if later_product and column == 0:
                    labels.append("A17")
                    centres.append(left_later_centre)
                for label, centre in zip(labels, centres, strict=True):
                    page.insert_text((left + 15, centre + 4), label, fontsize=10)
                    self.add_drawing(page, records, left, centre, f"C{column}-{label}")
            if later_product:
                page.insert_text((360, 430), "Compound B80: Preparation", fontsize=10)
                self.add_drawing(page, records, 360, 510, "LATER-B80")
            if raster:
                with fitz.open() as scanned:
                    target = scanned.new_page(width=660, height=720)
                    target.insert_image(
                        target.rect,
                        stream=page.get_pixmap(
                            matrix=fitz.Matrix(4, 4), alpha=False
                        ).tobytes("png"),
                    )
                    if native_conflict:
                        # An inconsistent embedded OCR text layer must not
                        # repaint or overwrite the original scanned title.
                        target.insert_text(
                            (360, 45), "Table B8. Compounds", fontsize=9, render_mode=3
                        )
                    scanned.save(original)
            else:
                document.save(original)
        with fitz.open(original) as document:
            for record in records:
                image = self.root / (record["structure_id"] + ".png")
                document[0].get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    clip=fitz.Rect(record["bbox_pdf"]),
                    alpha=False,
                ).save(image)
                record["image_path"] = str(image)
        metadata = self.root / "structures.json"
        metadata.write_text(
            json.dumps({"patent_number": "CONTROL-LATERAL", "structures": records})
        )
        result = bind(
            str(original),
            {"structure_candidate_pages": [0]},
            str(self.root / "bindings"),
            str(metadata),
        )
        payload = json.loads(Path(result["output_files"]["json"]).read_text())
        return result, payload

    @staticmethod
    def add_drawing(page, records, left, centre, identity):
        page.draw_polyline(
            [
                (left + 105, centre - 15),
                (left + 130, centre - 30),
                (left + 160, centre - 15),
                (left + 160, centre + 15),
                (left + 130, centre + 30),
                (left + 105, centre + 15),
                (left + 105, centre - 15),
            ],
            width=1.5,
        )
        page.draw_line((left + 160, centre - 15), (left + 205, centre - 25), width=1.5)
        records.append(
            {
                "structure_id": identity,
                "structure_index": len(records),
                "page_no": 1,
                "bbox_pdf": [left + 95, centre - 35, left + 235, centre + 35],
            }
        )

    def test_two_original_tables_keep_separate_titles_and_all_rows(self):
        result, payload = self.run_case()
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]},
            {"Compound 73", "Compound 28", "Compound 901A", "Compound I-003B"},
        )
        self.assertEqual(coverage_errors(payload), [])
        saved = json.loads(json.dumps(payload))
        self.assertEqual(
            len(read_compound_catalog(saved, saved["final_bindings"])[0]), 4
        )
        self.assertEqual(
            {
                qualified_table_key(s["source"]["header_scope"])
                for s in payload["source_sections"]
                if s["role"] == "structure_column_anchor"
            },
            {"TABLE11", "TABLEB8"},
        )
        for row in payload["final_bindings"]:
            evidence = row["numbered_table_cell_evidence"]
            expected = (
                "Table 11" if row["structure_id"].startswith("C0-") else "Table B8"
            )
            self.assertEqual(evidence["source_catalog"], expected)
            self.assertTrue(evidence["source_catalog_title"].startswith(expected + "."))

    def test_original_nonfinal_role_in_one_column_does_not_change_the_other(self):
        result, payload = self.run_case(nonfinal=True)
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertEqual(coverage_errors(payload), [])
        declarations = [
            scope
            for section in payload["source_sections"]
            if section["role"] == "structure_declaration_page"
            for scope in declaration_scopes(section["source"])
        ]
        self.assertEqual({s["role"] for s in declarations}, {"compound", "nonfinal"})
        for scope in declarations:
            prefix = "C0-" if scope["role"] == "compound" else "C1-"
            self.assertEqual(len(scope["diagrams"]), 2)
            self.assertTrue(all(d["id"].startswith(prefix) for d in scope["diagrams"]))

    def test_new_experiment_in_one_column_does_not_end_the_other_column(self):
        for centre in (510, 430):
            with self.subTest(centre=centre):
                result, payload = self.run_case(
                    later_product=True, left_later_centre=centre
                )
                self.assertEqual(
                    {r["cpd"] for r in result["bindings"]},
                    {
                        "Compound 73",
                        "Compound 28",
                        "Compound A17",
                        "Compound 901A",
                        "Compound I-003B",
                        "Compound B80",
                    },
                )
                self.assertEqual(coverage_errors(payload), [])

    def test_one_original_shared_nonfinal_title_keeps_the_existing_global_role(self):
        result, payload = self.run_case(shared_title=True)
        self.assertEqual(result["bindings"], [])
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(
            coverage_errors(payload),
            ["No proved printed-ID structure is available for formal processing."],
        )

    def test_scanned_parallel_tables_keep_the_same_original_roles(self):
        for nonfinal in (False, True):
            with self.subTest(nonfinal=nonfinal):
                result, payload = self.run_case(raster=True, nonfinal=nonfinal)
                self.assertEqual(len(result["bindings"]), 2 if nonfinal else 4)
                self.assertEqual(coverage_errors(payload), [])

    def test_native_conflict_in_one_scanned_column_does_not_poison_the_other(self):
        result, payload = self.run_case(
            raster=True, nonfinal=True, native_conflict=True
        )
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_saved_table_identifier_cannot_be_borrowed_from_its_neighbour(self):
        _, payload = self.run_case()
        saved = json.loads(json.dumps(payload))
        entry = next(
            r
            for r in saved["compound_catalog"]["entries"]
            if r["structure_id"].startswith("C0-")
        )
        entry["numbered_table_cell_evidence"]["source_catalog"] = "Table B8"
        with self.assertRaises(ValueError):
            reference_issues(saved, saved["compound_catalog"]["entries"])

    def test_rehashed_page_inventory_cannot_hide_a_context_neighbour(self):
        _, payload = self.run_case()
        saved = json.loads(json.dumps(payload))
        page = next(
            s
            for s in saved["source_sections"]
            if s["role"] == "structure_declaration_page"
        )
        page["source"]["page_grids"].pop()
        page["region_id"] = proof_id(page["source"])
        saved["source_reference_scope"] = reference_scope(
            saved["source_sections"],
            saved["source_reference_scope"]["original_pdf_sha256"],
        )
        saved["source_issues"] = []
        with self.assertRaises(ValueError):
            reference_issues(saved, saved["compound_catalog"]["entries"])

    def test_selected_reprint_retains_all_original_source_observations(self):
        result, payload = self.run_case(selected=True)
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        entries = payload["compound_catalog"]["entries"]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(len(r.get("additional_sources", [])) == 1 for r in entries))
        self.assertEqual(coverage_errors(payload), [])

    def test_selected_title_cannot_erase_novel_original_identifiers(self):
        result, payload = self.run_case(selected=True, selected_novel=True)
        labels = {r["cpd"] for r in result["bindings"]}
        self.assertIn("Compound I-003B", labels)
        self.assertNotIn("Compound 73", labels)
        self.assertTrue(coverage_errors(payload))

    def test_disagreeing_original_selected_scope_cannot_enable_reprint_exclusion(self):
        result, payload = self.run_case(
            selected=True, raster=True, native_conflict=True
        )
        self.assertNotIn("Compound 73", {r["cpd"] for r in result["bindings"]})
        self.assertTrue(coverage_errors(payload))

    def test_duplicate_numbers_in_distinct_full_tables_remain_ambiguous(self):
        result, payload = self.run_case(duplicate=True)
        self.assertNotIn("Compound 73", {r["cpd"] for r in result["bindings"]})
        self.assertTrue(coverage_errors(payload))


if __name__ == "__main__":
    unittest.main()
