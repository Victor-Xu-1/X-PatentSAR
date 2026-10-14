"""Original references must resolve to actual cells, never merely another page."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_source_roles import method_result_references

METHOD = (
    "Example 83: Binding assay\n"
    "Cells were seeded. Reagent was added. Plates were incubated.\n"
    "Results are shown in Table 72."
)


def original_fixture(
    root, method=METHOD, tables=(("Table 72", "IC50 (nM)"),), *, same_page=False
):
    pdf = root / "original.pdf"
    with fitz.open() as doc:
        if not same_page:
            doc.new_page().insert_text((40, 60), method, fontsize=10)
        for index, (caption, metric) in enumerate(tables):
            page = doc.new_page()
            shift = 130 if same_page and index == 0 else 0
            if shift:
                page.insert_text((40, 60), method, fontsize=10)
            page.insert_text(
                (40, 85 + shift), f"{caption}. Binding activity", fontsize=10
            )
            xs, ys = (
                [40, 105, 220],
                [100 + shift, 130 + shift, 160 + shift, 190 + shift],
            )
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            for row, fields in enumerate((("No.", metric), ("91", "4"), ("93", "8"))):
                for col, text in enumerate(fields):
                    page.insert_text((xs[col] + 3, ys[row] + 19), text, fontsize=9)
        doc.save(pdf)
    extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
    return load_json(root / "output" / "activity_data.json", None)


class ActivityResultReferenceTests(unittest.TestCase):
    def test_same_page_other_grid_cannot_hide_the_missing_named_result(self):
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(
                Path(temp), tables=(("Table 38", "Ki (nM)"),), same_page=True
            )
        self.assertTrue(activity_evidence_errors(data, [0]))
        self.assertEqual(data["coverage"]["references"][0]["status"], "missing")

    def test_proved_reference_window_and_actual_grid_can_share_one_page(self):
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(Path(temp), same_page=True)
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(data["coverage"]["references"][0]["status"], "resolved")

    def test_literal_reference_grammar_keeps_raw_table_identity(self):
        self.assertEqual(method_result_references(METHOD), ["Table 72"])
        for marker in ("Table 072", "Tabie72A", "Table B72", "表72"):
            source = METHOD.replace("Table 72", marker)
            self.assertEqual(
                method_result_references(source), [marker.replace("Tabie", "Table ")]
            )
        self.assertEqual(
            method_result_references(
                METHOD.replace("Results are shown in Table 72.", "结果见表72。")
            ),
            ["表72"],
        )
        self.assertEqual(method_result_references(METHOD + "\n" + "x" * 1024), [])

    def test_actual_native_facade_resolves_only_named_table(self):
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(Path(temp))
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        refs = data["coverage"]["references"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["table_id"], "Table 72")
        self.assertEqual(refs[0]["status"], "resolved")
        self.assertEqual(len(refs[0]["target_region_ids"]), 1)
        self.assertEqual(len(data["rows"]), 2)
        # This link proves presence, not assay conditions inherited from prose.
        self.assertTrue(
            all(
                r["activity_sources"][0]["assay"] == "Binding activity"
                for r in data["rows"]
            )
        )

    def test_existing_application_and_web_gate_use_same_serialized_reference_proof(
        self,
    ):
        from patent_sar_extractor.application.activity_policy import (
            _activity_acceptance_errors,
        )
        from patent_sar_extractor.web.acceptance import current

        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(Path(temp))
        self.assertTrue(current(data, "activity"))
        self.assertEqual(
            _activity_acceptance_errors(
                data, data["active_cpds"], classified_activity_pages=[0]
            ),
            [],
        )
        data["coverage"]["references"][0]["target_region_ids"] = []
        errors = _activity_acceptance_errors(
            data, data["active_cpds"], classified_activity_pages=[0]
        )
        self.assertTrue(any("Result-reference" in error for error in errors))

    def test_unrelated_successful_table_does_not_waive_missing_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(Path(temp), tables=(("Table 38", "Ki (nM)"),))
        self.assertTrue(activity_evidence_errors(data, [0]))
        ref = data["coverage"]["references"][0]
        self.assertEqual(ref["status"], "missing")
        self.assertEqual(ref["target_region_ids"], [])
        self.assertEqual(len(data["rows"]), 2)

    def test_reused_table_identity_is_ambiguous_not_nearest_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(
                Path(temp), tables=(("Table 72", "IC50 (nM)"), ("Table 72", "Ki (nM)"))
            )
        self.assertTrue(activity_evidence_errors(data, [0]))
        self.assertEqual(data["coverage"]["references"][0]["status"], "ambiguous")

    def test_merged_compound_rows_preserve_each_original_target(self):
        method = METHOD + "\nResults are listed in Table 38."
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(
                Path(temp), method, (("Table 72", "IC50 (nM)"), ("Table 38", "Ki (nM)"))
            )
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(
            [r["status"] for r in data["coverage"]["references"]],
            ["resolved", "resolved"],
        )
        self.assertTrue(all(len(r["activity_sources"]) == 2 for r in data["rows"]))

    def test_forged_serialized_link_is_recomputed_from_original_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            original = original_fixture(Path(temp))
        for change in ("target_region_ids", "table_id", "status"):
            data = copy.deepcopy(original)
            ref = data["coverage"]["references"][0]
            ref[change] = {
                "target_region_ids": [],
                "table_id": "Table 38",
                "status": "missing",
            }[change]
            with self.subTest(change=change), self.assertRaises(ValueError):
                activity_evidence_errors(data, [0])

    def test_matching_row_count_without_exact_source_cells_does_not_resolve(self):
        with tempfile.TemporaryDirectory() as temp:
            original = original_fixture(Path(temp))
        for defect in ("caption", "cell_geometry", "source_page", "source_value"):
            data = copy.deepcopy(original)
            source = data["rows"][0]["activity_sources"][0]
            if defect == "caption":
                source["raw_caption"] = "Table 38. Binding activity"
            elif defect == "cell_geometry":
                source["cells"][1]["bbox"] = [300, 200, 400, 220]
            elif defect == "source_page":
                source["page_no"] = 3
            else:
                source["cells"][1]["value"] = "19"
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                activity_evidence_errors(data, [0])

    def test_result_claims_unknown_ranges_and_local_rows_remain_unresolved(self):
        for claim in (
            "Compound 91 showed IC50 = 4 nM. Results are shown in Table 72.",
            "Results are shown in Tables 72-75.",
            "Results are shown in Table 72 and 75.",
            "Table 72. Binding activity\n91 4",
        ):
            method = METHOD.rsplit("Results", 1)[0] + claim
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as temp:
                data = original_fixture(Path(temp), method)
                self.assertTrue(activity_evidence_errors(data, [0]))

    def test_reference_only_method_cannot_resolve_another_method(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "original.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
                doc.new_page().insert_text(
                    (40, 60), METHOD.replace("83", "84"), fontsize=10
                )
                doc.save(pdf)
            extract(str(pdf), {"activity_pages": [0, 1]}, str(root / "output"))
            data = load_json(root / "output" / "activity_data.json", None)
        self.assertEqual(data["rows"], [])
        self.assertTrue(activity_evidence_errors(data, [0, 1]))
        self.assertTrue(
            all(r["status"] == "missing" for r in data["coverage"]["references"])
        )

    def test_actual_unruled_text_table_preserves_and_revalidates_original_row(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "original.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
                doc.new_page().insert_text(
                    (40, 60),
                    "Table 72. Binding activity\nNo. | IC50 (nM)\n91 | 4\n93 | ND",
                    fontsize=10,
                )
                doc.save(pdf)
            extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
            data = load_json(root / "output" / "activity_data.json", None)
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(data["coverage"]["references"][0]["status"], "resolved")
        self.assertEqual(data["rows"][1]["activity_values"]["IC50 (nM)"], "ND")
        source = data["rows"][0]["activity_sources"][0]
        for observation in source["cells"][1]["observations"]:
            observation["raw_text"] = "91 | 19"
        with self.assertRaises(ValueError):
            activity_evidence_errors(data, [0])

    def test_existing_native_biology_reader_retains_named_table_caption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "original.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
                page = doc.new_page()
                page.insert_text(
                    (40, 85), "Table 72. HTRF binding activity", fontsize=10
                )
                xs, ys = [40, 120, 220, 300], [100, 130, 160]
                for x in xs:
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((xs[0], y), (xs[-1], y))
                for row, fields in enumerate(
                    (("Compound ID", "HTRF Ratio", "Grade"), ("91", "0.13", "+++"))
                ):
                    for col, text in enumerate(fields):
                        page.insert_text((xs[col] + 3, ys[row] + 19), text, fontsize=8)
                doc.save(pdf)
            extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
            data = load_json(root / "output" / "activity_data.json", None)
        self.assertEqual(data["rows"][0]["source"], "observed_grid_cells")
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(data["coverage"]["references"][0]["status"], "resolved")

    def test_native_transposed_reader_resolves_using_original_column_cells(self):
        from tests.test_activity_transposed import transposed

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "original.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text(
                    (40, 60), METHOD.replace("Table 72", "Table 31"), fontsize=10
                )
                transposed(
                    doc.new_page(), ["Compound 91", "Ref. 1", "Compound 91", "Ref. 1"]
                )
                doc.save(pdf)
            extract(str(pdf), {"activity_pages": [0, 1]}, str(root / "output"))
            data = load_json(root / "output" / "activity_data.json", None)
        self.assertEqual(activity_evidence_errors(data, [0, 1]), [])
        self.assertEqual(data["coverage"]["references"][0]["status"], "resolved")

    def test_wrong_typed_contract_and_reference_reason_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as temp:
            original = original_fixture(Path(temp))
        data = copy.deepcopy(original)
        data["coverage"]["schema"]["version"] = float(
            data["coverage"]["schema"]["version"]
        )
        with self.assertRaises(ValueError):
            activity_evidence_errors(data, [0])
        from patent_sar_extractor.core.activity_coverage import source_record

        with self.assertRaises(ValueError):
            source_record(
                1,
                "grid",
                [1, 2, 3, 4],
                "Table 8",
                "Original",
                "parsed",
                "conflicting_result_references",
                1,
            )

    def test_source_and_target_resource_limits_fail_without_partial_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(Path(temp))
        for limit in (
            "MAX_SOURCE_PACKETS",
            "MAX_TARGETS_PER_REFERENCE",
            "MAX_REFERENCE_TARGETS",
        ):
            with (
                self.subTest(limit=limit),
                patch(
                    "patent_sar_extractor.core.activity_result_references." + limit, 0
                ),
                self.assertRaises(ValueError),
            ):
                activity_evidence_errors(data, [0])

    def test_locator_and_low_confidence_cannot_be_retagged_as_exact_row_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            original = original_fixture(Path(temp))
        for readings in (
            [{"method": "page_ocr_cell", "text": "4"}],
            [{"method": "cell_ocr_400dpi", "text": "4", "confidence": 0.2}],
            [{"method": "unknown_engine", "text": "4"}],
            [
                {"method": "native_cell", "text": "4"},
                {"method": "native_cell", "text": "19"},
            ],
        ):
            data = copy.deepcopy(original)
            data["rows"][0]["needs_review"] = False
            data["rows"][0]["activity_sources"][0]["cells"][1]["observations"] = (
                readings
            )
            with self.subTest(readings=readings), self.assertRaises(ValueError):
                activity_evidence_errors(data, [0])

    def test_complete_reference_inventory_cannot_be_removed_or_exceeded(self):
        with tempfile.TemporaryDirectory() as temp:
            data = original_fixture(Path(temp))
        stripped = copy.deepcopy(data)
        stripped["coverage"]["references"] = []
        with self.assertRaises(ValueError):
            activity_evidence_errors(stripped, [0])
        with (
            patch(
                "patent_sar_extractor.core.activity_result_references.MAX_REFERENCES", 0
            ),
            self.assertRaises(ValueError),
        ):
            activity_evidence_errors(data, [0])

    def test_native_and_cached_reference_disagreement_is_not_first_wins(self):
        from patent_sar_extractor.core.activity_coordinates import (
            extract_coordinate_tables,
        )

        with fitz.open() as doc:
            doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
            result = extract_coordinate_tables(
                doc, [0], page_texts={"0": METHOD.replace("Table 72", "Table 38")}
            )
        self.assertTrue(result.coverage)
        self.assertTrue(
            all(
                item["status"] == "unresolved"
                and item["reason"] == "conflicting_result_references"
                for item in result.coverage
            )
        )
