"""Native biology sources share the physical grid/continuation proof authority."""

import copy
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from tests.test_biology_activity_tables import table

HEAD = ["Example ID", "HuR degradation", "Example ID", "HuR degradation"]
AXES = [70, 170, 270, 370, 470]
METHOD = "Example 86: Degradation assay\nCells were seeded. Reagent was added.\nResults are shown in Table 54."


def root_table(doc, *, header_only=False, experiment=False):
    page = doc.new_page()
    page.insert_text(
        (70, 65), "KP4 cells were treated. Protein degradation by Western blot assay."
    )
    page.insert_text(
        (70, 80), "Table 54. Protein degradation measured by Western blot assay"
    )
    rows = [HEAD] if header_only else [HEAD, ["31", "A", "32", "D"]]
    table(page, AXES, [100 + 25 * i for i in range(len(rows) + 1)], rows)
    if experiment:
        page.insert_text((70, 400), "Example 95: New cell proliferation assay")
        page.insert_text(
            (70, 420), "Other cells were plated. A different reagent was added."
        )
    return page


def dataset(temp, mode="rows", *, header_only=False, experiment=False):
    path = temp / "original.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((40, 60), METHOD, fontsize=10)
        root_table(doc, header_only=header_only, experiment=experiment)
        page = doc.new_page()
        if mode == "caption":
            page.insert_text((70, 55), "Table 54 (continued)")
        rows = (
            [HEAD, ["33", "B", "34", "C"]]
            if mode == "header"
            else [["33", "B", "34", "C"]]
        )
        table(page, AXES, [75 + 25 * i for i in range(len(rows) + 1)], rows)
        doc.save(path)
    extract(str(path), {"activity_pages": [0]}, str(temp / "output"))
    return load_json(temp / "output/activity_data.json", None)


class BiologyGridOwnershipTests(unittest.TestCase):
    def test_literal_table_typography_and_real_identifier_headers_share_roles(self):
        for caption, identity in (
            ("Table A7. Cereblon binding measured in the HTRF assay", "Table A7"),
            ("Tabie 62. Cereblon binding measured in the HTRF assay", "Table 62"),
            ("表 7. Cereblon binding measured in the HTRF assay", "表 7"),
        ):
            with self.subTest(caption=caption), fitz.open() as doc:
                page = doc.new_page()
                if caption.startswith("表"):
                    page.insert_font(fontname="china-s")
                    page.insert_text((70, 80), caption, fontname="china-s", fontsize=9)
                else:
                    page.insert_text((70, 80), caption)
                table(
                    page,
                    [70, 190, 300, 410],
                    [100, 125, 150],
                    [["No.", "Ratio", "Grade"], ["73B", "0.15", "++"]],
                )
                result = extract_coordinate_tables(doc, [0])
            self.assertEqual(result.rows[0].table_id, identity)
            self.assertEqual(
                result.rows[0].activity_values,
                {"Cereblon HTRF ratio": "0.15", "Cereblon HTRF grade": "++"},
            )

    def test_new_experiment_boundary_prevents_biology_context_borrowing(self):
        with fitz.open() as doc:
            root_table(doc, experiment=True)
            page = doc.new_page()
            table(
                page,
                AXES,
                [75, 100, 125],
                [["33", "B", "34", "C"], ["35", "A", "36", "D"]],
            )
            result = extract_coordinate_tables(doc, [0, 1])
        self.assertEqual([r.cpd for r in result.rows], ["Compound 31", "Compound 32"])
        self.assertTrue(
            any(
                r["page_no"] == 2 and r["status"] == "unresolved"
                for r in result.coverage
            )
        )

    def test_every_legal_continuation_keeps_exact_header_context_and_fields(self):
        for mode in ("rows", "header", "caption"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                data = dataset(Path(temp), mode)
                self.assertEqual(activity_evidence_errors(data, [0]), [])
                self.assertEqual(
                    [r["cpd"] for r in data["rows"]],
                    ["Compound 31", "Compound 32", "Compound 33", "Compound 34"],
                )
                self.assertEqual(
                    data["coverage"]["references"][0]["status"], "resolved"
                )
                self.assertEqual(
                    len(data["coverage"]["references"][0]["target_region_ids"]), 2
                )
                for row in data["rows"]:
                    self.assertEqual(row["source"], "observed_grid_cells")
                    source = row["activity_sources"][0]
                    self.assertEqual(source["target"], "HuR")
                    self.assertEqual(source["cell_line"], "KP4")
                    self.assertEqual(source["assay"], "Western blot")
                    self.assertEqual(source["header_region"]["page_no"], 2)
                    self.assertIn("Table 54", source["raw_caption"])
                    self.assertTrue(
                        all("physical_column" in c for c in source["cells"])
                    )

    def test_header_only_split_requires_real_connected_biology_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            data = dataset(Path(temp), header_only=True)
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        self.assertEqual(
            [r["cpd"] for r in data["rows"]], ["Compound 33", "Compound 34"]
        )
        self.assertTrue(
            any(r["status"] == "header" for r in data["coverage"]["regions"])
        )

    def test_serialized_biology_cells_and_roles_cannot_be_forged(self):
        with tempfile.TemporaryDirectory() as temp:
            original = dataset(Path(temp))
        for field, value in (
            ("physical_column", 0),
            ("value", "G"),
            ("bbox", [70, 75, 170, 100]),
        ):
            data = copy.deepcopy(original)
            data["rows"][-1]["activity_sources"][0]["cells"][1][field] = value
            with self.subTest(field=field):
                try:
                    errors = activity_evidence_errors(data, [0])
                except (ValueError, TypeError):
                    continue
                self.assertTrue(errors)

    def test_biology_and_numeric_tables_remain_distinct_sources(self):
        with fitz.open() as doc:
            root_table(doc)
            page = doc.new_page()
            page.insert_text((70, 55), "Table 62. Target: BET; Assay: binding")
            table(
                page,
                [70, 170, 270],
                [75, 100, 125],
                [["Example ID", "IC50 (nM)"], ["55A", "0.9"]],
            )
            result = extract_coordinate_tables(doc, [0, 1])
        self.assertEqual(result.rows[-1].cpd, "Compound 55A")
        self.assertEqual(result.rows[-1].activity_values, {"IC50 (nM)": "0.9"})
        self.assertEqual(result.rows[-1].activity_sources[0]["target"], "BET")

    def test_original_grades_and_missing_values_are_not_inferred_or_dropped(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 56. Protein degradation measured by Western blot assay"
            )
            table(
                page,
                [70, 190, 310],
                [100, 125, 150, 175],
                [["Example ID", "HuR degradation"], ["42B", "G"], ["42C", "ND"]],
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual([r.cpd for r in result.rows], ["Compound 42B", "Compound 42C"])
        self.assertEqual(
            [next(iter(r.activity_values.values())) for r in result.rows], ["G", "ND"]
        )
        self.assertTrue(all(not r.needs_review for r in result.rows))

    def test_known_grade_role_cannot_relabel_an_original_numeric_reading(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "original.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text(
                    (70, 80),
                    "Table 56. Protein degradation measured by Western blot assay",
                )
                table(
                    page,
                    [70, 190, 310],
                    [100, 125, 150],
                    [["Example ID", "HuR degradation"], ["42B", "0.2"]],
                )
                doc.save(path)
            extract(str(path), {"activity_pages": [0]}, str(root / "output"))
            data = load_json(root / "output/activity_data.json", None)
        self.assertEqual(next(iter(data["rows"][0]["activity_values"].values())), "0.2")
        self.assertTrue(data["rows"][0]["needs_review"])
        data["rows"][0]["needs_review"] = False
        self.assertTrue(activity_evidence_errors(data, [0]))

    def test_repeated_pairs_with_different_printed_targets_cannot_be_last_wins(self):
        with fitz.open() as doc:
            page = root_table(doc, header_only=True)
            # Use a fresh independent source with differing original column roles.
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 55. Protein degradation measured by Western blot assay"
            )
            table(
                page,
                AXES,
                [100, 125, 150],
                [
                    ["Example ID", "HuR degradation", "Example ID", "STAT degradation"],
                    ["44", "A", "45", "B"],
                ],
            )
            result = extract_coordinate_tables(doc, [page.number])
        self.assertEqual([r.cpd for r in result.rows], ["Compound 44", "Compound 45"])
        self.assertTrue(all(r.needs_review for r in result.rows))
        self.assertTrue(
            all(r.activity_sources[0]["target"] is None for r in result.rows)
        )

    def test_explicit_context_conflict_cannot_be_hidden_by_biology_roles(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 56. Target: EGFR; Protein degradation by Western blot"
            )
            table(
                page,
                [70, 190, 310],
                [100, 125, 150],
                [["Example ID", "HuR degradation"], ["42B", "A"]],
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(result.rows[0].activity_sources[0]["target"], "EGFR")
        self.assertTrue(result.rows[0].needs_review)

    def test_biology_role_resolution_never_erases_original_declared_units(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 52. Cereblon binding measured in the HTRF assay"
            )
            table(
                page,
                [70, 190, 300, 410],
                [100, 125, 150],
                [["Example ID", "Ratio (nM)", "Grade (%)"], ["37A", "0.15", "93"]],
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(
            result.rows[0].activity_values, {"Ratio (nM)": "0.15", "Grade (%)": "93"}
        )
        self.assertEqual(result.coverage[0]["layout"]["semantic_kind"], "generic")
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 54. Protein degradation measured by Western blot assay"
            )
            table(
                page,
                [70, 190, 310],
                [100, 125, 150],
                [["Example ID", "HuR degradation (nM)"], ["42B", "0.15"]],
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(result.coverage[0]["layout"]["semantic_kind"], "generic")
        self.assertTrue(next(iter(result.rows[0].activity_values)).endswith("(nM)"))

    def test_actual_existing_ocr_raster_uses_same_source_and_component_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with fitz.open() as drawing:
                page = drawing.new_page()
                table(
                    page,
                    [70, 190, 300, 410],
                    [100, 125, 150],
                    [["Example ID", "Ratio", "Grade"], ["37A", "0.15", "+++"]],
                )
                rectangle = fitz.Rect(68, 98, 412, 152)
                image = page.get_pixmap(
                    matrix=fitz.Matrix(3, 3), clip=rectangle, alpha=False
                ).tobytes("png")
            path = root / "original.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_image(rectangle, stream=image)
                page.insert_text(
                    (70, 80), "Table 52. Cereblon binding measured in the HTRF assay"
                )
                page.insert_text((60, 780), "Original native footer")
                doc.save(path)
            extract(str(path), {"activity_pages": [0]}, str(root / "output"))
            data = load_json(root / "output/activity_data.json", None)
        self.assertEqual([r["cpd"] for r in data["rows"]], ["Compound 37A"])
        self.assertEqual(
            data["rows"][0]["activity_values"],
            {"Cereblon HTRF ratio": "0.15", "Cereblon HTRF grade": "+++"},
        )
        self.assertFalse(
            data["rows"][0]["needs_review"], data["rows"][0]["activity_sources"]
        )
        self.assertEqual(activity_evidence_errors(data, [0]), [])
        sources = data["rows"][0]["activity_sources"][0]["cells"]
        self.assertTrue(
            any(o["method"] == "cell_ocr_400dpi" for o in sources[1]["observations"])
        )
        self.assertTrue(
            any(
                o["method"] == "printed_cross_components"
                for o in sources[2]["observations"]
            )
        )
