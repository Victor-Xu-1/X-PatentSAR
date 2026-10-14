"""Existing-engine raster count columns with real original/native geometry."""

import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from tests.test_activity_parser_modules import draw_grid


def raster_counts(*, shadow="", second_count="2"):
    doc = fitz.open()
    original = doc.new_page()
    draw_grid(
        original,
        [["No.", "IC50 (nM)", "n"], ["73", "12.4", "3"], ["58", "9.1", second_count]],
    )
    clip = fitz.Rect(58, 98, 467, 177)
    image = original.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False)
    page = doc.new_page()
    page.insert_image(clip, stream=image.tobytes("png"))
    page.insert_text((60, 85), "Table 87. Binding activity", fontsize=9)
    page.insert_text((60, 780), "Original native footer", fontsize=9)
    if shadow:
        page.insert_text((337, 140), shadow, fontsize=9, render_mode=3)
    return doc, page.number


class ActivityMetadataNativeTests(unittest.TestCase):
    def test_actual_native_facade_writer_and_read_acceptance_keep_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "original-control.pdf"
            with fitz.open() as doc:
                draw_grid(
                    doc.new_page(),
                    [
                        ["No.", "IC50 (nM)", "Sample size"],
                        ["73", "12.4", "3"],
                        ["58", "9.1", "2"],
                    ],
                )
                doc.save(path)
            result = extract(str(path), {"activity_pages": [0]}, str(root / "out"))
            payload = json.loads((root / "out/activity_data.json").read_text())
            self.assertEqual(result["n_rows"], 2)
            self.assertEqual(activity_evidence_errors(payload, [0]), [])
            self.assertEqual(
                [
                    r["activity_sources"][0]["cells"][-1]["metadata_kind"]
                    for r in payload["rows"]
                ],
                ["sample_count", "sample_count"],
            )
            self.assertEqual(
                [r["activity_values"] for r in payload["rows"]],
                [{"IC50 (nM)": "12.4"}, {"IC50 (nM)": "9.1"}],
            )

    def test_empty_original_raster_count_is_proved_missing_not_invented(self):
        doc, index = raster_counts(second_count="")
        with doc:
            result = extract_coordinate_tables(doc, [index])
        row = next(r for r in result.rows if r.cpd == "Compound 58")
        self.assertEqual(row.activity_values, {"IC50 (nM)": "9.1"})
        self.assertFalse(row.needs_review)
        count = row.activity_sources[0]["cells"][-1]
        self.assertEqual(count["value"], "")
        self.assertEqual(count["metadata_status"], "missing")
        self.assertTrue(
            any(
                o.get("method") == "cell_ocr_400dpi"
                and o.get("ink_crop_pixels", "unobserved") is None
                for o in count["observations"]
            )
        )

    def test_actual_raster_count_is_not_an_endpoint_with_native_footer(self):
        doc, index = raster_counts()
        with doc:
            result = extract_coordinate_tables(doc, [index])
        self.assertEqual([r.cpd for r in result.rows], ["Compound 73", "Compound 58"])
        self.assertEqual(
            [r.activity_values for r in result.rows],
            [{"IC50 (nM)": "12.4"}, {"IC50 (nM)": "9.1"}],
        )
        self.assertFalse(any(r.needs_review for r in result.rows))
        metadata = [r.activity_sources[0]["cells"][-1] for r in result.rows]
        self.assertEqual([c["value"] for c in metadata], ["3", "2"])
        self.assertTrue(all(c["metadata_status"] == "observed" for c in metadata))
        self.assertTrue(
            all(
                any(o["method"] == "cell_ocr_400dpi" for o in c["observations"])
                for c in metadata
            )
        )

    def test_actual_native_and_raster_count_disagreement_cannot_become_clean(self):
        doc, index = raster_counts(shadow="4")
        with doc:
            result = extract_coordinate_tables(doc, [index])
        row = next(r for r in result.rows if r.cpd == "Compound 73")
        self.assertTrue(row.needs_review)
        self.assertEqual(row.activity_values, {"IC50 (nM)": "12.4"})
        count = row.activity_sources[0]["cells"][-1]
        self.assertEqual(count["metadata_status"], "unresolved")
        self.assertTrue(any(o["text"] == "4" for o in count["observations"]))
        self.assertTrue(any(o["text"] == "3" for o in count["observations"]))
