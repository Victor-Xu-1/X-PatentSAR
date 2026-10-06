from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.structure_binder import bind


class SpatialBindingAuthorityTests(unittest.TestCase):
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
                    "patent_sar_extractor.core.binding_source_headings._precompute_visible_label_cache",
                    side_effect=AssertionError("redundant crop OCR"),
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
            self.assertEqual(result["bound"], 2)
            self.assertEqual(result["patent_id"], "controlled")
            self.assertTrue(
                all(b["patent_id"] == "controlled" for b in result["bindings"])
            )
            self.assertEqual(result["detected_style"], "original_cell_caption_heading")
            self.assertEqual(
                [b["cpd"] for b in result["bindings"]], ["Compound 1", "Compound 2"]
            )
            self.assertTrue(
                all(b["accuracy_status"] == "confirmed" for b in result["bindings"])
            )
            serialized = json.loads(Path(result["output_files"]["json"]).read_text())
            self.assertEqual(serialized["final_bindings"], result["bindings"])
            with Path(result["output_files"]["csv"]).open(newline="") as stream:
                self.assertEqual(
                    [r["cpd"] for r in csv.DictReader(stream)],
                    ["Compound 1", "Compound 2"],
                )


if __name__ == "__main__":
    unittest.main()
