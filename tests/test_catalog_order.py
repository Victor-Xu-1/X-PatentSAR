"""Printed dash/suffix identifiers use one stable natural ordering."""

import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.structure_binder import bind


class CatalogOrderTests(unittest.TestCase):
    def test_dashes_are_not_concatenated_into_another_number(self):
        labels = ["10", "2", "1-2", "1", "8B", "8A", "1-1"]
        with tempfile.TemporaryDirectory(prefix="original-catalog-order-") as temporary:
            root = Path(temporary)
            original, metadata, records = (
                root / "source.pdf",
                root / "structures.json",
                [],
            )
            with fitz.open() as document:
                page = document.new_page(width=400, height=780)
                page.insert_text((40, 60), "Table 7. Compounds", fontsize=10)
                ys = [80, 110, *(200 + 90 * i for i in range(len(labels)))]
                for x in (40, 180, 350):
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((40, y), (350, y))
                page.insert_text((50, 100), "Compound No.", fontsize=10)
                page.insert_text((210, 100), "Structure", fontsize=10)
                for index, label in enumerate(labels):
                    y = ys[index + 1]
                    page.insert_text((60, y + 35), label, fontsize=10)
                    page.draw_polyline(
                        [
                            (210, y + 30),
                            (240, y + 15),
                            (270, y + 30),
                            (270, y + 55),
                            (240, y + 70),
                            (210, y + 55),
                            (210, y + 30),
                        ],
                        color=(0, 0, 0),
                        width=1.5,
                    )
                    bounds = [200, y + 10, 290, y + 75]
                    image = root / f"s{index}.png"
                    page.get_pixmap(
                        clip=fitz.Rect(bounds), matrix=fitz.Matrix(2, 2)
                    ).save(image)
                    records.append(
                        {
                            "structure_id": f"s{index}",
                            "structure_index": index,
                            "page_no": 1,
                            "bbox_pdf": bounds,
                            "image_path": str(image),
                        }
                    )
                document.save(original)
            metadata.write_text(
                json.dumps({"patent_number": "CONTROLLED-ORDER", "structures": records})
            )
            result = bind(
                str(original), {"bind_workers": 1}, str(root / "bound"), str(metadata)
            )
            self.assertEqual(result["source_issues"], [])
        self.assertEqual(
            [r["cpd"] for r in result["compound_catalog"]["entries"]],
            [
                "Compound 1",
                "Compound 1-1",
                "Compound 1-2",
                "Compound 2",
                "Compound 8A",
                "Compound 8B",
                "Compound 10",
            ],
        )
