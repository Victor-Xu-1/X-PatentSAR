"""Focused real native-PDF controls, ownership and downstream artifact contracts."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_identity import (
    normalize_compound,
    normalize_value,
)
from patent_sar_extractor.core.activity_models import ParsedActivity
from patent_sar_extractor.core.activity_observations import merge_rows
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.web.artifacts import _activities


def draw_grid(page, rows, *, caption="Table 81. Target: ALK; Assay: binding", top=100):
    xs = [60 + 135 * column for column in range(len(rows[0]) + 1)]
    ys = [top + 25 * row for row in range(len(rows) + 1)]
    if caption:
        page.insert_text((60, top - 15), caption, fontsize=9)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    for column in reversed(range(len(rows[0]))):
        for row, cells in enumerate(rows):
            if cells[column]:
                page.insert_text(
                    (xs[column] + 7, ys[row] + 15), cells[column], fontsize=9
                )


class ActivityParserModuleTests(unittest.TestCase):
    def test_reordered_native_headers_bind_values_to_cells_not_token_order(self):
        with fitz.open() as doc:
            page = doc.new_page()
            draw_grid(
                page, [["No.", "ALK Dmax (%)", "EGFR DC50 (uM)"], ["42B", "85", "17"]]
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(result.rows[0].cpd, "Compound 42B")
        self.assertEqual(
            result.rows[0].activity_values,
            {"ALK Dmax (%)": "85", "EGFR DC50 (uM)": "17"},
        )
        source = result.rows[0].activity_sources[0]
        self.assertEqual(source["target"], "ALK")
        self.assertEqual(source["assay"], "binding")
        self.assertTrue(all(cell["bbox"] for cell in source["cells"]))

    def test_numeric_cell_with_missing_neighbor_never_shifts(self):
        with fitz.open() as doc:
            page = doc.new_page()
            draw_grid(page, [["No.", "IC50 (nM)", "Dmax (%)"], ["42", "", "80"]])
            row = extract_coordinate_tables(doc, [0]).rows[0]
        self.assertEqual(row.activity_values, {"IC50 (nM)": "", "Dmax (%)": "80"})
        self.assertTrue(row.needs_review)

    def test_native_dashed_id_is_not_parent_or_suffix_relabelled(self):
        with fitz.open() as doc:
            page = doc.new_page()
            draw_grid(page, [["No.", "IC50 (nM)"], ["4-2A", "17"]])
            row = extract_coordinate_tables(doc, [0]).rows[0]
        self.assertEqual(row.cpd, "Compound 4-2A")
        self.assertFalse(row.needs_review)

    def test_recognized_empty_grid_owns_page_without_rows(self):
        with fitz.open() as doc:
            page = doc.new_page()
            draw_grid(page, [["No.", "IC50 (nM)"], ["", ""]])
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(result.owned_pages, {0})
        self.assertEqual(result.rows, [])

    def test_unresolved_printed_id_is_not_guessed_from_values(self):
        with fitz.open() as doc:
            page = doc.new_page()
            draw_grid(page, [["No.", "IC50 (nM)"], ["?", "17"]])
            with self.assertRaisesRegex(RuntimeError, "Unresolved compound ID"):
                extract_coordinate_tables(doc, [0])

    def test_continuation_requires_adjacent_page_and_same_geometry(self):
        for supplied in ([0, 1], [0, 2]):
            with self.subTest(supplied=supplied), fitz.open() as doc:
                draw_grid(doc.new_page(), [["No.", "IC50 (nM)"], ["42", "17"]])
                doc.new_page()
                next_page = doc[1] if supplied[-1] == 1 else doc.new_page()
                draw_grid(next_page, [["43B", "29"], ["44", "31"]], caption="", top=75)
                rows = extract_coordinate_tables(doc, supplied).rows
                self.assertEqual(len(rows), 3 if supplied[-1] == 1 else 1)

    def test_new_caption_never_borrows_previous_text_target_or_unit(self):
        result = extract_text_tables(
            [0, 1],
            {
                "0": "Table 8. EGFR HTRF assay\nNo. EGFR IC50 (nM)\n42 17",
                "1": "Table 9. BRAF assay\nNo. BRAF DC50\n42 29",
            },
        )
        self.assertEqual(
            result.rows[1].activity_values, {"BRAF DC50 (unit unknown)": "29"}
        )
        self.assertNotIn("EGFR", str(result.rows[1].activity_sources))

    def test_text_continuation_cannot_cross_gap_or_owned_page(self):
        text = {"0": "Table 8 assay\nNo. IC50 (nM)\n42 17", "2": "43 29"}
        result = extract_text_tables([0, 2], text)
        self.assertEqual([r.cpd for r in result.rows], ["Compound 42"])

    def test_repeated_observations_survive_web_read_without_public_dto_change(self):
        result = extract_text_tables(
            [0, 1],
            {
                "0": "Table 8 Assay: binding\nNo. IC50 (nM)\n42 17",
                "1": "Table 9 Assay: binding\nNo. IC50 (nM)\n42 29",
            },
        )
        rows = merge_rows(result.rows)
        projected = [
            activity
            for row in rows
            for activity in _activities(asdict(row), page_count=2)
        ]
        self.assertEqual([(a.value, a.page) for a in projected], [("17", 1), ("29", 2)])

    def test_empty_classified_set_cannot_trigger_document_scan_or_pseudo_compound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "control.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((70, 80), "Table 81. No. IC50 (nM) Compound 42 17")
                doc.save(pdf)
            with patch(
                "patent_sar_extractor.core.activity_extractor.page_text",
                side_effect=AssertionError("no scan"),
            ):
                result = extract(str(pdf), {"activity_pages": []}, str(root / "out"))
            self.assertEqual(result["rows"], [])
            self.assertEqual(
                json.loads((root / "out/activity_data.json").read_text())[
                    "active_cpds"
                ],
                [],
            )

    def test_empty_owned_grid_is_not_reparsed_as_cached_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "control.pdf"
            with fitz.open() as doc:
                draw_grid(doc.new_page(), [["No.", "IC50 (nM)"], ["", ""]])
                doc.save(pdf)
            with patch(
                "patent_sar_extractor.core.activity_extractor.extract_text_tables",
                return_value=ParsedActivity(),
            ) as text:
                result = extract(str(pdf), {"activity_pages": [0]}, str(root / "out"))
            self.assertEqual(result["n_rows"], 0)
            self.assertEqual(text.call_args.args[0], [])

    def test_identity_and_thresholds_are_lossless(self):
        self.assertEqual(normalize_compound("Compound 42"), "Compound 42")
        self.assertEqual(normalize_compound("I-42B"), "Compound I-42B")
        self.assertEqual(normalize_value("80%"), "80%")
        self.assertEqual(normalize_value("<=17"), "<=17")
        self.assertEqual(normalize_value("4]"), "4]")

    def test_missing_classification_is_not_proof_of_no_activity(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "Malformed classified"),
        ):
            extract("not-opened.pdf", {}, temporary)

    def test_dependency_graph_is_acyclic_with_no_facade_back_import(self):
        import patent_sar_extractor.core.activity_extractor as facade

        directory = Path(facade.__file__).parent
        files = [
            directory / "activity_extractor.py",
            *sorted(directory.glob("activity_*.py")),
        ]
        graph = {}
        for file in set(files):
            tree = ast.parse(file.read_text())
            imports = {
                node.module.rsplit(".", 1)[-1]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            if file.stem != "activity_extractor":
                self.assertNotIn("activity_extractor", imports)
            graph[file.stem] = imports
            if file.stem != "activity_values":
                self.assertLess(len(file.read_text().splitlines()), 400)

        def visit(name, active):
            self.assertNotIn(name, active)
            for dependency in graph.get(name, set()) & graph.keys():
                visit(dependency, active | {name})

        visit("activity_extractor", set())


if __name__ == "__main__":
    unittest.main()
