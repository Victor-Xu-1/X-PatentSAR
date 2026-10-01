from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.structure_page_locator import (
    _covered_active_cpds,
    locate_structure_pages,
)


class NumberedTableLocatorTests(unittest.TestCase):
    def test_flattened_punctuated_ids_are_not_chemical_locants_or_child_ids(self):
        text = "Table B Cmpd No. Structure Cmpd No. Structure 31. HN 32. NH 33."
        hits = _covered_active_cpds(
            [2],
            {2: text},
            ["Compound 31", "Compound 32", "Compound 33", "Compound 31A"],
        )
        self.assertEqual(
            hits, {"Compound 31": [2], "Compound 32": [2], "Compound 33": [2]}
        )

    def test_numbered_structure_table_edges_are_not_trimmed_as_non_series_prose(self):
        texts = [
            "Table B Cmpd No. Structure Cmpd No. Structure 31. HN 32. NH 33.",
            "Cmpd No. Structure Cmpd No. Structure 34. HN 35. NH 36.",
            "Example 31 synthesis was carried out using 1 mg of reagent; MS m/z 350.2.",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "controlled.pdf"
            with fitz.open() as doc:
                for text in texts:
                    doc.new_page().insert_text((70, 80), text, fontsize=8)
                doc.save(pdf)
            cache = Path(temporary) / "cache.json"
            write_json_atomic(
                cache,
                {
                    "page_texts": {str(p): t for p, t in enumerate(texts)},
                    "ocr_line_map": {},
                },
            )
            result = locate_structure_pages(
                str(pdf),
                {"synthesis_pages": [2], "candidate_pages": [2]},
                [f"Compound {n}" for n in range(31, 37)],
                ocr_cache_path=str(cache),
            )
            self.assertEqual(result["structure_table_pages"], [0, 1])
            self.assertEqual(result["selected_pages"], [0, 1])
            self.assertEqual(result["structure_table_coverage_count"], 6)


if __name__ == "__main__":
    unittest.main()
