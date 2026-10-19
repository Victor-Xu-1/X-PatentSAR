"""Actual binder controls: declarations cover IDs but never assign diagram order."""

import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.structure_binder import bind
from tests import test_binding_modules as binding_controls


class HeadingMappingTests(unittest.TestCase):
    def test_catalogue_does_not_hide_an_unmapped_heading_on_the_same_page(self):
        with tempfile.TemporaryDirectory(
            prefix="patentsar-heading-catalogue-"
        ) as temporary:
            root = Path(temporary)
            pdf, metadata, profile = binding_controls.BindingModuleTests().pdf_fixture(
                root
            )
            with fitz.open(pdf) as document:
                document[0].insert_text((50, 370), "Compounds 1 and 72C", fontsize=11)
                document.saveIncr()
            result = bind(str(pdf), profile, str(root / "bindings"), str(metadata))
        self.assertEqual(
            {row["cpd"] for row in result["compound_catalog"]["entries"]},
            {"Compound 1", "Compound 2"},
        )
        self.assertEqual(
            {row["cpd"] for row in result["source_issues"]},
            {"Compound 1", "Compound 72C"},
            "A matching ID above this separate declaration cannot discharge its occurrence",
        )
        self.assertTrue(
            any(
                section.get("identifiers") == ["1", "72C"]
                for section in result["source_sections"]
            )
        )

    def original(self, root, *, captions=True):
        pdf = root / "source.pdf"
        structures = []
        with fitz.open() as document:
            page = document.new_page(width=600, height=650)
            page.insert_text((45, 55), "Compounds 17 and 18", fontsize=12)
            for index, (label, left) in enumerate((("18", 70), ("17", 340)), 1):
                page.draw_polyline(
                    [
                        (left + 20, 120),
                        (left + 60, 100),
                        (left + 100, 120),
                        (left + 100, 160),
                        (left + 60, 180),
                        (left + 20, 160),
                        (left + 20, 120),
                    ],
                    color=(0, 0, 0),
                    width=1.5,
                )
                bounds = [left, 85, left + 160, 195]
                image = root / f"source-{index}.png"
                page.get_pixmap(
                    matrix=fitz.Matrix(2, 2), clip=fitz.Rect(bounds), alpha=False
                ).save(image)
                if captions:
                    page.insert_text((left + 25, 215), f"Compound {label}", fontsize=11)
                structures.append(
                    {
                        "structure_id": f"S{index}",
                        "structure_index": index,
                        "page_no": 1,
                        "bbox_pdf": bounds,
                        "image_path": str(image),
                    }
                )
            document.save(pdf)
        metadata = root / "structures.json"
        metadata.write_text(
            json.dumps(
                {"patent_number": "CONTROLLED-HEADINGS", "structures": structures}
            )
        )
        return pdf, metadata

    def test_printed_captions_win_over_the_opposite_heading_member_order(self):
        with tempfile.TemporaryDirectory(
            prefix="patentsar-heading-mapping-"
        ) as temporary:
            root = Path(temporary)
            pdf, metadata = self.original(root)
            result = bind(
                str(pdf), {"bind_workers": 1}, str(root / "bindings"), str(metadata)
            )
        self.assertEqual(result["source_issues"], [])
        self.assertEqual(
            {
                row["cpd"]: row["structure_id"]
                for row in result["compound_catalog"]["entries"]
            },
            {"Compound 18": "S1", "Compound 17": "S2"},
        )

    def test_two_unlabelled_diagrams_never_acquire_the_title_order(self):
        with tempfile.TemporaryDirectory(
            prefix="patentsar-heading-unlabelled-"
        ) as temporary:
            root = Path(temporary)
            pdf, metadata = self.original(root, captions=False)
            result = bind(
                str(pdf), {"bind_workers": 1}, str(root / "bindings"), str(metadata)
            )
        self.assertEqual(result["compound_catalog"]["entries"], [])
        self.assertEqual(
            {row["cpd"] for row in result["source_issues"]},
            {"Compound 17", "Compound 18"},
        )


if __name__ == "__main__":
    unittest.main()
