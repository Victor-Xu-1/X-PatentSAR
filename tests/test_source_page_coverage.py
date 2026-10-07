"""No-model original-PDF controls for discovered tables and unclassified continuations."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions


def grid(page, xs, ys, rows):
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            page.insert_text((xs[column] + 7, ys[row] + 15), value, fontsize=9)


class SourcePageCoverageTests(unittest.TestCase):
    def test_unmarked_source_tables_and_continuations_are_discovered(self):
        for declared in ([], [0]):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original = root / "source.pdf"
                structures, texts, lines = [], {}, {}
                with fitz.open() as doc:
                    for page_number, numbers in enumerate(((17,), (18, 19))):
                        page = doc.new_page()
                        if page_number == 0:
                            ys = [90, 115, 215]
                            rows = [["Cmpd No.", "Structure"], ["17.", ""]]
                            data_top = 125
                        else:
                            ys = [75, 175, 275]
                            rows = [["18.", ""], ["19.", ""]]
                            data_top = 85
                        grid(page, [50, 100, 280], ys, rows)
                        for row, number in enumerate(numbers):
                            top = data_top + row * 100
                            bounds = (110.0, float(top), 265.0, float(top + 80))
                            page.draw_line((130, top + 25), (160, top + 40))
                            page.draw_line((160, top + 40), (190, top + 25))
                            image = root / f"segment-{number}.png"
                            page.get_pixmap(clip=fitz.Rect(bounds)).save(image)
                            structures.append(
                                {
                                    "structure_id": f"S{number:04}",
                                    "structure_index": len(structures),
                                    "page_no": page_number + 1,
                                    "bbox_pdf": bounds,
                                    "image_path": str(image),
                                }
                            )
                        texts[page_number] = page.get_text("text")
                        lines[page_number] = [
                            {"y0": word[1], "text": word[4]}
                            for word in page.get_text("words")
                        ]
                    doc.save(original)
                metadata = root / "metadata.json"
                metadata.write_text(
                    json.dumps({"patent_number": "CONTROL", "structures": structures})
                )
                with (
                    patch(
                        "patent_sar_extractor.core.binding_preparation._get_ocr_line_coords",
                        side_effect=AssertionError("native lines already supplied"),
                    ),
                    patch(
                        "patent_sar_extractor.core.structure_binder.observed_heading_blocks",
                        side_effect=AssertionError(
                            "numbered cells already own sources"
                        ),
                    ),
                    patch(
                        "patent_sar_extractor.core.structure_binder.select_heading_bindings",
                        side_effect=AssertionError("competing heading path"),
                    ),
                ):
                    result = bind(
                        str(original),
                        {
                            "structure_candidate_pages": [0, 1],
                            "authoritative_structure_table_pages": declared,
                            "active_cpds": [],
                            "ocr_text_map": texts,
                            "ocr_line_map": lines,
                        },
                        str(root / "bound"),
                        str(metadata),
                    )
                self.assertEqual(
                    [row["cpd"] for row in result["bindings"]],
                    ["Compound 17", "Compound 18", "Compound 19"],
                )
                self.assertEqual(result["bound"], 3)
                self.assertTrue(
                    all(
                        row["accuracy_status"] == "confirmed"
                        for row in result["bindings"]
                    )
                )
                artifact = json.loads(Path(result["output_files"]["json"]).read_text())
                self.assertEqual(
                    artifact["authoritative_structure_table_pages"], [0, 1]
                )


class ActivityPageCoverageTests(unittest.TestCase):
    def test_biology_report_headers_use_observed_experiment_context(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 65),
                "KP4 cells were treated. Protein degradation by Western blot assay.",
            )
            page.insert_text(
                (70, 80), "Table 54. Protein degradation measured by Western blot assay"
            )
            grid(
                page,
                [70, 170, 270, 370, 470],
                [100, 125, 150],
                [
                    ["Example ID", "HuR degradation", "Example ID", "HuR degradation"],
                    ["31", "A", "32", "D"],
                ],
            )
            result = extract_coordinate_tables(doc, [0])
        observed = {key for row in result.rows for key in row.activity_values}
        self.assertEqual(observed, {"KP4 HuR degradation grade"})
        self.assertEqual(set(result.headers), observed)

    def _generic(self, doc, *, caption=True, shifted=False):
        page = doc.new_page()
        xs = [60, 195, 330]
        if shifted:
            xs = [x + 30 for x in xs]
        if caption:
            page.insert_text(
                (60, 85), "Table 81. Target: ALK; Assay: binding", fontsize=9
            )
            grid(page, xs, [100, 125, 150], [["No.", "IC50 (nM)"], ["42", "17"]])
        else:
            grid(page, xs, [75, 100, 125], [["43B", "29"], ["44", "31"]])

    def test_unclassified_adjacent_scalar_table_is_read_by_original_cells(self):
        with fitz.open() as doc:
            self._generic(doc)
            self._generic(doc, caption=False)
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(
            [row.cpd for row in result.rows],
            ["Compound 42", "Compound 43B", "Compound 44"],
        )
        self.assertEqual([row.page_no for row in result.rows], [1, 2, 2])
        self.assertEqual(
            [row.activity_values["IC50 (nM)"] for row in result.rows],
            ["17", "29", "31"],
        )
        self.assertEqual(result.owned_pages, {0, 1})

    def test_unclassified_biology_continuation_keeps_ratio_grade_and_sources(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 52. Cereblon binding measured in the HTRF assay"
            )
            xs = [70, 190, 300, 410]
            grid(
                page,
                xs,
                [100, 125, 150],
                [["Example ID", "Ratio", "Grade"], ["37A", "0.15", "++"]],
            )
            grid(
                doc.new_page(),
                xs,
                [75, 100, 125],
                [["38B", "0.29", "+"], ["39", "0.07", "+++"]],
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(
            [row.cpd for row in result.rows],
            ["Compound 37A", "Compound 38B", "Compound 39"],
        )
        self.assertEqual(
            [row.activity_values["Cereblon HTRF ratio"] for row in result.rows],
            ["0.15", "0.29", "0.07"],
        )
        self.assertEqual(
            [row.activity_values["Cereblon HTRF grade"] for row in result.rows],
            ["++", "+", "+++"],
        )
        self.assertEqual(result.rows[-1].activity_sources[0]["page_no"], 2)
        self.assertTrue(all(not row.needs_review for row in result.rows))

    def test_empty_classification_does_not_start_an_all_document_scan(self):
        with fitz.open() as doc:
            self._generic(doc)
            with patch(
                "patent_sar_extractor.core.activity_coordinates.detect_ruled_table_regions",
                side_effect=AssertionError("no seed"),
            ):
                result = extract_coordinate_tables(doc, [])
        self.assertEqual(result.rows, [])

    def test_gap_stops_continuation_before_unclassified_lookalike(self):
        with fitz.open() as doc:
            self._generic(doc)
            self._generic(doc, caption=False)
            doc.new_page()
            self._generic(doc, caption=False)
            with patch(
                "patent_sar_extractor.core.activity_coordinates.detect_ruled_table_regions",
                wraps=detect_ruled_table_regions,
            ) as detector:
                result = extract_coordinate_tables(doc, [0])
                scanned = [call.args[0].number for call in detector.call_args_list]
        self.assertEqual(scanned, [0, 1, 2])
        self.assertEqual(result.owned_pages, {0, 1})

    def test_mismatched_geometry_does_not_borrow_previous_assay(self):
        with fitz.open() as doc:
            self._generic(doc)
            self._generic(doc, caption=False, shifted=True)
            self._generic(doc, caption=False)
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual([row.cpd for row in result.rows], ["Compound 42"])
        self.assertEqual(result.owned_pages, {0})


if __name__ == "__main__":
    unittest.main()
