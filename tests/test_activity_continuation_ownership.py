"""Native original scopes: legal continuations, source boundaries and rejection."""

import copy
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from tests.test_activity_parallel_grids import panel

METHOD = (
    "Example 68: Binding assay\nCells were seeded. Reagent was added.\n"
    "Results are shown in Table 71."
)
HEAD = ["No.", "IC50 (nM)", "Dmax (%)"]


def add_root(doc, *, header_only=False, new_experiment=False):
    page = doc.new_page()
    page.insert_text((40, 80), "Table 71. Target: JAK; Assay: binding", fontsize=9)
    panel(page, 40, 100, [HEAD] if header_only else [HEAD, ["7", "3", "90"]])
    if new_experiment:
        page.insert_text((40, 400), "Example 92: Cell proliferation assay", fontsize=10)
        page.insert_text(
            (40, 420), "Cells were plated. A different reagent was added.", fontsize=10
        )
    return page


def facade(root, mode="rows", *, header_only=False):
    pdf = root / "original.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
        add_root(doc, header_only=header_only)
        page = doc.new_page()
        if mode == "caption":
            page.insert_text((40, 70), "Table 71 (continued)", fontsize=9)
        elif mode == "new_caption":
            page.insert_text(
                (40, 70), "Table 92. Target: BET; Assay: binding", fontsize=9
            )
        rows = (
            [HEAD, ["19", "4", "80"]]
            if mode in {"header", "new_caption"}
            else [["19", "4", "80"]]
        )
        panel(page, 40, 90, rows)
        doc.save(pdf)
    extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
    return load_json(root / "output" / "activity_data.json", None)


class ContinuationOwnershipTests(unittest.TestCase):
    def test_all_legal_adjacent_modes_share_one_proved_scope(self):
        for mode in ("rows", "header", "caption"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                data = facade(Path(temp), mode)
                self.assertEqual(activity_evidence_errors(data, [0]), [])
                self.assertEqual(
                    [r["cpd"] for r in data["rows"]], ["Compound 7", "Compound 19"]
                )
                ref = data["coverage"]["references"][0]
                self.assertEqual(ref["status"], "resolved")
                self.assertEqual(len(ref["target_region_ids"]), 2)
                self.assertTrue(
                    all(
                        source["assay"] == "binding"
                        for row in data["rows"]
                        for source in row["activity_sources"]
                    )
                )

    def test_new_experiment_after_previous_grid_stops_headerless_borrowing(self):
        with fitz.open() as doc:
            add_root(doc, new_experiment=True)
            page = doc.new_page()
            panel(page, 40, 90, [["19", "4", "80"]])
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual([r.cpd for r in result.rows], ["Compound 7"])
        self.assertTrue(
            any(
                r["page_no"] == 2 and r["status"] == "unresolved"
                for r in result.coverage
            )
        )

    def test_parallel_panels_and_adjacent_panels_keep_unique_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "original.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
                page = add_root(doc)
                panel(page, 220, 100, [["9", "5", "80"]])
                page = doc.new_page()
                panel(page, 40, 90, [["15", "7", "70"]])
                panel(page, 220, 90, [["20", "9", "55"]])
                doc.save(pdf)
            extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
            data = load_json(root / "output" / "activity_data.json", None)
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(len(data["rows"]), 4)
        self.assertEqual(len(data["coverage"]["references"][0]["target_region_ids"]), 4)

    def test_repeated_parallel_headers_belong_to_the_same_original_caption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "original.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
                page = add_root(doc)
                panel(page, 220, 100, [HEAD, ["9", "5", "80"]])
                doc.save(pdf)
            extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
            data = load_json(root / "output" / "activity_data.json", None)
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(len(data["coverage"]["references"][0]["target_region_ids"]), 2)

    def test_every_grid_row_is_revalidated_even_without_a_method_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            original = facade(Path(temp))
        original["coverage"]["regions"] = [
            r for r in original["coverage"]["regions"] if r["status"] != "reference"
        ]
        original["coverage"]["references"] = []
        original["coverage"]["seed_pages"] = [1]
        original["coverage"]["discovered_pages"] = [1]
        self.assertEqual(activity_evidence_errors(original, [1]), [])
        for field, value in (
            ("physical_column", 0),
            ("bbox", [40, 90, 70, 114]),
        ):
            data = copy.deepcopy(original)
            data["rows"][-1]["activity_sources"][0]["cells"][1][field] = value
            with self.subTest(field=field):
                self.assertTrue(activity_evidence_errors(data, [1]))
        data = copy.deepcopy(original)
        data["rows"].pop()
        self.assertTrue(activity_evidence_errors(data, [1]))

    def test_malformed_header_layout_is_a_controlled_validation_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            original = facade(Path(temp), header_only=True)
        for layout in ({}, {"ys": []}, "foreign", {"data_start": True}):
            data = copy.deepcopy(original)
            grid = next(
                r for r in data["coverage"]["regions"] if r["status"] == "header"
            )
            grid["layout"] = layout
            with self.subTest(layout=layout), self.assertRaises(ValueError):
                activity_evidence_errors(data, [0])

    def test_unknown_or_missing_saved_cell_proof_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as temp:
            original = facade(Path(temp))
        for field, value in (
            ("cells", "foreign"),
            ("cells", [None]),
            ("page_no", {}),
            ("table_bbox", None),
        ):
            data = copy.deepcopy(original)
            data["rows"][0]["activity_sources"][0][field] = value
            with self.subTest(field=field):
                try:
                    errors = activity_evidence_errors(data, [0])
                except (ValueError, TypeError):
                    continue
                self.assertTrue(errors)
        data = copy.deepcopy(original)
        for region in data["coverage"]["regions"]:
            region.pop("layout", None)
        from patent_sar_extractor.application.activity_policy import (
            _activity_acceptance_errors,
            _extract_active_cpds,
        )

        self.assertTrue(
            _activity_acceptance_errors(
                data, _extract_active_cpds(data), classified_activity_pages=[0]
            )
        )

    def test_independent_roots_are_not_a_single_truncated_resource_scope(self):
        from patent_sar_extractor.core.activity_coverage import source_record
        from patent_sar_extractor.core.activity_table_scopes import layout_scope_errors

        with tempfile.TemporaryDirectory() as temp:
            data = facade(Path(temp))
        template = next(
            r
            for r in data["coverage"]["regions"]
            if r.get("layout") and r["page_no"] == 2
        )
        regions = []
        for page in range(1, 301):
            layout = copy.deepcopy(template["layout"])
            layout["header_origin"]["page_no"] = page
            regions.append(
                source_record(
                    page,
                    "grid",
                    template["bbox"],
                    template["table_id"],
                    template["header"],
                    "parsed",
                    "original_cells",
                    1,
                    layout=layout,
                )
            )
        self.assertEqual(layout_scope_errors(regions), [])

    def test_same_number_but_independent_caption_context_remains_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "original.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
                page = add_root(doc)
                page.insert_text(
                    (220, 80), "Table 71. Target: BET; Assay: binding", fontsize=9
                )
                panel(page, 220, 100, [HEAD, ["19", "4", "80"]])
                doc.save(pdf)
            extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
            data = load_json(root / "output" / "activity_data.json", None)
        self.assertEqual(
            [row["activity_sources"][0]["target"] for row in data["rows"]],
            ["JAK", "BET"],
        )
        self.assertEqual(data["coverage"]["references"][0]["status"], "ambiguous")
        self.assertTrue(activity_evidence_errors(data, [0]))

    def test_source_gate_is_shared_by_web_and_application_consumers(self):
        from patent_sar_extractor.application.activity_policy import (
            _activity_acceptance_errors,
            _extract_active_cpds,
        )
        from patent_sar_extractor.web.acceptance import authority
        from tests.test_web_acceptance import complete_payloads

        with tempfile.TemporaryDirectory() as temp:
            data = facade(Path(temp))
        active = _extract_active_cpds(data)
        self.assertEqual(
            _activity_acceptance_errors(data, active, classified_activity_pages=[0]), []
        )
        data["rows"][-1]["activity_sources"][0]["cells"][1]["physical_column"] = 0
        self.assertTrue(
            _activity_acceptance_errors(data, active, classified_activity_pages=[0])
        )
        payloads = complete_payloads()
        payloads["activity"] = {**data, "active_cpds": active}
        result, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "failed")
        self.assertIn("grid row and cell", str(result.errors))

    def test_header_only_start_needs_actual_connected_result_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            data = facade(Path(temp), header_only=True)
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual([r["cpd"] for r in data["rows"]], ["Compound 19"])
        self.assertTrue(
            any(r["status"] == "header" for r in data["coverage"]["regions"])
        )

    def test_new_caption_creates_independent_source_and_never_inherits_target(self):
        with tempfile.TemporaryDirectory() as temp:
            data = facade(Path(temp), "new_caption")
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(data["rows"][1]["activity_sources"][0]["target"], "BET")
        self.assertEqual(data["rows"][1]["table_id"], "Table 92")
        self.assertEqual(len(data["coverage"]["references"][0]["target_region_ids"]), 1)

    def test_serialized_prefix_origin_and_geometry_cannot_forge_a_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            original = facade(Path(temp))
        for field, value in (
            ("prefix", "Example 92: New binding assay"),
            ("suffix", "New assay starts here"),
            ("xs", [40, 110, 140, 200]),
            ("header_origin", {"page_no": 99, "bbox": [40, 100, 200, 124]}),
        ):
            data = copy.deepcopy(original)
            grids = [r for r in data["coverage"]["regions"] if r["kind"] == "grid"]
            selected = grids[0] if field == "suffix" else grids[-1]
            selected["layout"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                activity_evidence_errors(data, [0])

    def test_changed_columns_caption_and_page_gap_are_not_continuations(self):
        for mode in ("width", "caption", "gap"):
            with self.subTest(mode=mode), fitz.open() as doc:
                add_root(doc)
                if mode == "gap":
                    doc.new_page()
                page = doc.new_page()
                if mode == "caption":
                    page.insert_text((40, 70), "Table 92. Different assay", fontsize=9)
                panel(
                    page,
                    40,
                    90,
                    [["19", "4", "80"]],
                    widths=(55, 45, 60) if mode == "width" else (35, 65, 60),
                )
                result = extract_coordinate_tables(doc, [0, len(doc) - 1])
            self.assertEqual([r.cpd for r in result.rows], ["Compound 7"])
            self.assertTrue(any(r["status"] == "unresolved" for r in result.coverage))
