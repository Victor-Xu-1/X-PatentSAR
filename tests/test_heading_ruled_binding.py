"""Actual original source -> binder/writer -> saved coverage and web consumers."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.errors import WebError


def run_original(root, *, raster, image_directory=None):
    source = root / "original.pdf"
    image = (image_directory or root) / "structure.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        page = document.new_page(width=360, height=360)
        page.insert_text((70, 90), "Compound 82A", fontsize=9.5)
        words = page.get_text("words")
        y0, y1 = min(word[1] for word in words), max(word[3] for word in words)
        page.draw_rect(fitz.Rect(50, y0 - 1, 240, y1 + 1.5), width=0.4)
        bounds = [80, 115, 210, 205]
        page.draw_polyline(
            [
                (100, 135),
                (130, 120),
                (160, 135),
                (160, 175),
                (130, 190),
                (100, 175),
                (100, 135),
            ],
            width=1.5,
        )
        page.insert_text((40, 245), "Step 1: Reaction", fontsize=10)
        page.get_pixmap(
            clip=fitz.Rect(bounds), matrix=fitz.Matrix(2, 2), alpha=False
        ).save(image)
        if raster:
            pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            )
            with fitz.open() as scanned:
                scan = scanned.new_page(width=360, height=360)
                scan.insert_image(scan.rect, stream=pixels)
                scan.insert_text((40, 340), "Native footer only", fontsize=8)
                scanned.save(source)
        else:
            document.save(source)
    metadata = root / "structures.json"
    metadata.write_text(
        json.dumps(
            {
                "patent_number": "CONTROLLED-RULED-HEADING",
                "structures": [
                    {
                        "structure_id": "synthetic-ring",
                        "structure_index": 1,
                        "page_no": 1,
                        "bbox_pdf": bounds,
                        "image_path": str(image),
                    }
                ],
            }
        )
    )
    result = bind(
        str(source),
        {"structure_candidate_pages": [0]},
        str(root / "bindings"),
        str(metadata),
    )
    return result, load_json(Path(result["output_files"]["json"]), {})


class HeadingRuledBindingTests(unittest.TestCase):
    def test_actual_binder_and_saved_consumers_keep_exact_original_owner(self):
        for raster in (False, True):
            with (
                self.subTest(raster=raster),
                tempfile.TemporaryDirectory(
                    prefix="original-ruled-binding-"
                ) as temporary,
            ):
                result, payload = run_original(Path(temporary), raster=raster)
                self.assertEqual(result["bound"], 1, payload["source_issues"])
                self.assertEqual(payload["source_issues"], [])
                self.assertEqual(
                    [b["cpd"] for b in payload["final_bindings"]], ["Compound 82A"]
                )
                self.assertEqual(
                    reference_issues(payload, payload["compound_catalog"]["entries"]),
                    [],
                )
                self.assertEqual(coverage_errors(payload), [])
                entries, _ = read_compound_catalog(payload, payload["final_bindings"])
                self.assertEqual([entry["cpd"] for entry in entries], ["Compound 82A"])
                proof = payload["final_bindings"][0]["original_heading_evidence"][
                    "heading_observation"
                ]
                self.assertEqual(proof["version"], 2 if raster else 1)
                for mutation in (
                    "source_metadata",
                    "source_owner",
                    "source_position",
                    "primary_proof",
                ):
                    changed = copy.deepcopy(payload)
                    entry = changed["compound_catalog"]["entries"][0]
                    block = entry["original_heading_evidence"]
                    if mutation == "source_metadata":
                        block["heading_observation"]["original_pdf_sha256"] = "b" * 64
                    elif mutation == "source_owner":
                        block["cpd"] = "Compound 83B"
                    elif mutation == "source_position":
                        block["bbox"][0] += 1
                    else:
                        entry["original_heading_structure_evidence"]["heading_source"][
                            "original_pdf_sha256"
                        ] = "b" * 64
                    with self.subTest(mutation=mutation):
                        with self.assertRaises((ValueError, WebError)):
                            read_compound_catalog(changed, changed["final_bindings"])
                        with self.assertRaises(ValueError):
                            coverage_errors(changed)


if __name__ == "__main__":
    unittest.main()
