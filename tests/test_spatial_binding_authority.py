from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.structure_binder import bind
from tests.test_caption_role_raster import raster_catalog


class SpatialBindingAuthorityTests(unittest.TestCase):
    def test_dense_scanned_caption_catalogue_reaches_writer_without_activity_hints(
        self,
    ):
        labels = ("17B", "172", "902AB")
        with tempfile.TemporaryDirectory(prefix="dense-source-writer-") as temporary:
            root = Path(temporary)
            pdf = root / "controlled.pdf"
            original, observed, _boxes = raster_catalog(
                prefixed=True,
                labels=labels,
                label_height=14,
                label_fontname="hebo",
            )
            structures = []
            with original:
                for index, diagram in enumerate(observed[1]):
                    bounds = [diagram[axis] for axis in ("x0", "y0", "x1", "y1")]
                    image = root / f"diagram-{index}.png"
                    original[0].get_pixmap(clip=fitz.Rect(bounds)).save(image)
                    structures.append(
                        {
                            "structure_id": diagram["id"],
                            "structure_index": index,
                            "page_no": 1,
                            "bbox_pdf": bounds,
                            "image_path": str(image),
                        }
                    )
                original.save(pdf)
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps({"patent_number": "controlled", "structures": structures})
            )
            with patch(
                "patent_sar_extractor.core.binding_source_headings.observe_heading",
                wraps=observe_heading,
            ) as heading_reader:
                result = bind(
                    str(pdf),
                    {"active_cpds": [], "structure_candidate_pages": [0]},
                    str(root / "bindings"),
                    str(metadata),
                )
            saved = load_json(Path(result["output_files"]["json"]), {})
        self.assertEqual(
            {row["cpd"] for row in saved["compound_catalog"]["entries"]},
            {f"Compound {label}" for label in labels},
            saved["source_issues"],
        )
        self.assertEqual(
            saved["source_issues"],
            [],
            {
                "issues": saved["source_issues"],
                "captions": [
                    (row["cpd"], row["exact_caption_evidence"]["bbox"])
                    for row in saved["compound_catalog"]["entries"]
                ],
                "headings": [
                    (section.get("identifier"), section.get("bbox"))
                    for section in saved["source_sections"]
                    if "heading_observation" in section
                ],
            },
        )
        self.assertEqual(
            len(saved["source_reference_scope"]["label_reference_ids"]), len(labels)
        )
        self.assertEqual(heading_reader.call_count, 0)
        self.assertEqual(coverage_errors(saved), [])
        entries, _ = read_catalog_entries(saved)
        self.assertEqual(len(entries), len(labels))
        self.assertTrue(
            all(
                row["accuracy_status"] == "confirmed"
                for row in saved["compound_catalog"]["entries"]
            )
        )

    def test_complete_original_cells_bypass_all_competing_repair_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "controlled.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                for x in (50, 100, 280):
                    page.draw_line((x, 90), (x, 315))
                for y in (90, 115, 215, 315):
                    page.draw_line((50, y), (280, y))
                page.insert_text((53, 105), "Cmpd No.", fontsize=7)
                page.insert_text((140, 105), "Structure", fontsize=9)
                structures = []
                for number, y0 in ((1, 125), (2, 225)):
                    page.insert_text((65, y0 + 30), f"{number}.", fontsize=10)
                    bounds = (110.0, float(y0), 265.0, float(y0 + 80))
                    image = root / f"segment-{number}.png"
                    page.get_pixmap(clip=fitz.Rect(bounds)).save(image)
                    structures.append(
                        {
                            "structure_id": f"S{number:04}",
                            "structure_index": number - 1,
                            "page_no": 1,
                            "bbox_pdf": bounds,
                            "image_path": str(image),
                        }
                    )
                doc.save(pdf)
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps({"patent_number": "controlled", "structures": structures})
            )
            with (
                patch(
                    "patent_sar_extractor.core.structure_binder.observed_heading_blocks",
                    wraps=observed_heading_blocks,
                ) as inventory,
                patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    side_effect=AssertionError("redundant native crop OCR"),
                ),
                patch(
                    "patent_sar_extractor.core.structure_binder.select_heading_bindings",
                    side_effect=AssertionError("competing repair"),
                ),
            ):
                result = bind(
                    str(pdf),
                    {
                        "active_cpds": ["Compound 1", "Compound 2"],
                        "structure_candidate_pages": [0],
                        "authoritative_structure_table_pages": [0],
                        "authoritative_structure_table_cpds": [
                            "Compound 1",
                            "Compound 2",
                        ],
                    },
                    str(root / "bindings"),
                    str(metadata),
                )
            self.assertEqual(inventory.call_args.args[1], [0])
            self.assertEqual(result["bound"], 2)
            self.assertEqual(result["patent_id"], "controlled")
            self.assertTrue(
                all(
                    b["patent_id"] == "controlled"
                    for b in result["compound_catalog"]["entries"]
                )
            )
            self.assertEqual(result["detected_style"], "original_cell_caption_heading")
            self.assertEqual(
                [b["cpd"] for b in result["compound_catalog"]["entries"]],
                ["Compound 1", "Compound 2"],
            )
            self.assertTrue(
                all(
                    b["accuracy_status"] == "confirmed"
                    for b in result["compound_catalog"]["entries"]
                )
            )
            serialized = load_json(Path(result["output_files"]["json"]), {})
            self.assertEqual(
                serialized["compound_catalog"]["entries"],
                result["compound_catalog"]["entries"],
            )
            with Path(result["output_files"]["csv"]).open(newline="") as stream:
                self.assertEqual(
                    [r["cpd"] for r in csv.DictReader(stream)],
                    ["Compound 1", "Compound 2"],
                )


if __name__ == "__main__":
    unittest.main()
