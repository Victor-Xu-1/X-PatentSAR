"""A proved original label cell is not another independent synthesis heading."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.caption_label_roles import (
    caption_label_index,
    caption_label_reference,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.errors import WebError


class HeadingLabelRoleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="original-label-role-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_binding(self, *, raster=False, extra_heading=False):
        source = self.root / "original.pdf"
        structures = []
        with fitz.open() as document:
            page = document.new_page(width=500, height=600)
            page.insert_text((40, 75), "Table 47. Compounds", fontsize=10)
            for x in (40, 180, 320):
                page.draw_line((x, 95), (x, 225))
            for y in (95, 125, 225):
                page.draw_line((40, y), (320, y))
            page.insert_text((55, 116), "Compound 17", fontsize=9)
            page.insert_text((195, 116), "Compound 18", fontsize=9)
            page.insert_text((40, 300), "Compound 19: Preparation", fontsize=11)
            page.insert_text((40, 455), "Step 1: Reaction", fontsize=10)
            if extra_heading:
                page.insert_text((40, 505), "Compound 17: Preparation", fontsize=11)
            for number, bounds in (
                (17, (55, 140, 165, 215)),
                (18, (195, 140, 305, 215)),
                (19, (65, 320, 185, 415)),
            ):
                x0, y0, _x1, y1 = bounds
                page.draw_polyline(
                    [
                        (x0 + 15, y0 + 20),
                        (x0 + 40, y0 + 5),
                        (x0 + 70, y0 + 20),
                        (x0 + 70, y1 - 20),
                        (x0 + 40, y1 - 5),
                        (x0 + 15, y1 - 20),
                        (x0 + 15, y0 + 20),
                    ],
                    color=(0, 0, 0),
                    width=1.5,
                )
                image = self.root / f"S{number}.png"
                page.get_pixmap(
                    clip=fitz.Rect(bounds), matrix=fitz.Matrix(2, 2), alpha=False
                ).save(image)
                structures.append(
                    {
                        "structure_id": f"S{number}",
                        "structure_index": number,
                        "page_no": 1,
                        "bbox_pdf": bounds,
                        "image_path": str(image),
                    }
                )
            if raster:
                pixels = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
                with fitz.open() as scanned:
                    image_page = scanned.new_page(width=500, height=600)
                    image_page.insert_image(
                        image_page.rect, stream=pixels.tobytes("png")
                    )
                    scanned.save(source)
            else:
                document.save(source)
        metadata = self.root / "structures.json"
        metadata.write_text(
            json.dumps({"patent_number": "CONTROLLED-ROLES", "structures": structures})
        )
        result = bind(
            str(source),
            {"structure_candidate_pages": [0]},
            str(self.root / "bindings"),
            str(metadata),
        )
        return (
            source,
            result,
            load_json(Path(result["output_files"]["json"]), {}),
        )

    def test_full_binder_preserves_true_heading_but_reuses_exact_label_cell_roles(self):
        with patch(
            "patent_sar_extractor.core.binding_source_headings.observe_heading",
            wraps=observe_heading,
        ) as observer:
            _, result, payload = self.run_binding()
        self.assertEqual(observer.call_count, 1)
        self.assertEqual(result["bound"], 3, payload["source_issues"])
        self.assertEqual(payload["source_issues"], [])
        headings = [
            s["identifier"]
            for s in payload["source_sections"]
            if s["role"] == "compound_heading"
        ]
        self.assertEqual(
            headings,
            ["19"],
            "Exact caption cells must not become synthesis declarations",
        )
        references = [
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_label_reference"
        ]
        self.assertEqual([s["identifier"] for s in references], ["17", "18"])
        self.assertEqual(
            reference_issues(payload, payload["compound_catalog"]["entries"]), []
        )
        self.assertEqual(coverage_errors(payload), [])
        entries, _ = read_compound_catalog(payload, payload["final_bindings"])
        self.assertEqual(
            [e["cpd"] for e in entries], ["Compound 17", "Compound 18", "Compound 19"]
        )

    def test_raster_caption_roles_reuse_the_original_cell_proof_not_heading_rereads(
        self,
    ):
        with patch(
            "patent_sar_extractor.core.binding_source_headings.observe_heading",
            wraps=observe_heading,
        ) as observer:
            _, result, payload = self.run_binding(raster=True)
        self.assertEqual(
            result["bound"],
            3,
            {
                "issues": payload["source_issues"],
                "headings": [
                    {
                        "role": s["role"],
                        "id": s.get("identifier"),
                        "status": s.get("status"),
                        "reads": [
                            r.get("raw_text")
                            for r in s.get("heading_observation", {}).get(
                                "observations", []
                            )
                        ],
                    }
                    for s in payload["source_sections"]
                ],
            },
        )
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(observer.call_count, 1)
        self.assertEqual(
            sum(
                s["role"] == "structure_label_reference"
                for s in payload["source_sections"]
            ),
            2,
        )
        self.assertEqual(
            reference_issues(payload, payload["compound_catalog"]["entries"]), []
        )

    def test_repeated_literal_cannot_close_a_different_missing_heading_occurrence(self):
        _, _, payload = self.run_binding(extra_heading=True)
        payload["source_issues"] = []
        gaps = reference_issues(payload, payload["compound_catalog"]["entries"])
        self.assertTrue(
            any(
                gap["reason"] == "original_heading_identifier_without_proved_structure"
                and gap["cpd"] == "Compound 17"
                for gap in gaps
            ),
            gaps,
        )
        self.assertTrue(coverage_errors(payload))

    def test_same_identifier_elsewhere_on_same_page_remains_a_heading_observation(self):
        source, _, payload = self.run_binding(extra_heading=True)
        with fitz.open(source) as document:
            sections = []
            blocks = observed_heading_blocks(
                document,
                [0],
                {},
                source_sections=sections,
                source_bindings=payload["compound_catalog"]["entries"],
            )
        self.assertEqual([b["cpd"] for b in blocks], ["Compound 19", "Compound 17"])
        self.assertEqual(
            [
                s["identifier"]
                for s in sections
                if s["role"] == "structure_label_reference"
            ],
            ["17", "18"],
        )

    def test_invalid_or_foreign_caption_proofs_do_not_exempt_original_headings(self):
        source, _, payload = self.run_binding()
        for mutation in ("foreign", "geometry", "legacy", "conflict"):
            entries = copy.deepcopy(payload["compound_catalog"]["entries"])
            entry = next(e for e in entries if e["cpd"] == "Compound 17")
            if mutation == "foreign":
                entry["source_pdf_sha256"] = "f" * 64
            elif mutation == "geometry":
                entry["exact_caption_evidence"]["bbox"][0] += 1
            elif mutation == "legacy":
                entry["binding_rule"] = "authoritative_structure_table_sequence"
            else:
                entry["exact_caption_evidence"]["observations"][0]["text"] = (
                    "Compound 99"
                )
            with self.subTest(mutation=mutation), fitz.open(source) as document:
                blocks = observed_heading_blocks(
                    document, [0], {}, source_bindings=entries
                )
            self.assertEqual([b["cpd"] for b in blocks], ["Compound 17", "Compound 19"])

    def test_saved_references_recheck_geometry_literal_identity_and_exact_source(self):
        _, _, original = self.run_binding()
        for mutation in ("bbox", "text", "source", "page", "document"):
            payload = copy.deepcopy(original)
            reference = next(
                s
                for s in payload["source_sections"]
                if s["role"] == "structure_label_reference"
            )
            if mutation == "bbox":
                reference["bbox"] = [350, 400, 450, 420]
            elif mutation == "text":
                reference["line_text"] = "Compound 99"
                reference["identifier"] = "99"
            elif mutation == "source":
                reference["source_key"] = "f" * 64
            elif mutation == "page":
                reference["page_no"] = True
            else:
                reference["original_pdf_sha256"] = "f" * 64
            payload["source_reference_scope"] = reference_scope(
                payload["source_sections"],
                original["source_reference_scope"]["original_pdf_sha256"],
            )
            with (
                self.subTest(mutation=mutation),
                self.assertRaisesRegex(ValueError, "label-role reference ownership"),
            ):
                reference_issues(payload, payload["compound_catalog"]["entries"])
            with self.assertRaises(ValueError):
                coverage_errors(payload)
            with self.assertRaises(WebError):
                read_compound_catalog(payload, payload["final_bindings"])

    def test_cleared_removed_or_downgraded_role_references_are_not_success(self):
        _, _, original = self.run_binding()
        for mutation in ("removed", "downgraded", "missing_source"):
            payload = copy.deepcopy(original)
            payload["source_issues"] = []
            if mutation == "removed":
                payload["source_sections"] = [
                    s
                    for s in payload["source_sections"]
                    if s["role"] != "structure_label_reference"
                ]
            elif mutation == "downgraded":
                payload["source_reference_scope"]["version"] = 4
                payload["source_reference_scope"].pop("label_reference_ids")
            else:
                payload["compound_catalog"]["entries"] = payload["compound_catalog"][
                    "entries"
                ][1:]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                reference_issues(payload, payload["compound_catalog"]["entries"])

    def test_unknown_frame_or_wide_locator_cannot_create_a_caption_role(self):
        _, _, payload = self.run_binding()
        index = caption_label_index(
            payload["compound_catalog"]["entries"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )
        reference = next(
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_label_reference"
        )
        line = {
            "text": reference["line_text"],
            "bbox": reference["bbox"],
            "source": reference["line_source"],
            "geometry_space": "rendered",
        }
        for field, value in (
            ("geometry_space", "locator"),
            ("bbox", [0, 100, 500, 125]),
            ("bbox", None),
            ("source", []),
        ):
            with self.subTest(field=field, value=value):
                self.assertIsNone(
                    caption_label_reference({**line, field: value}, 1, index)
                )

    def test_caption_locators_share_existing_cell_edge_and_centre_ownership(self):
        _, _, payload = self.run_binding()
        index = caption_label_index(
            payload["compound_catalog"]["entries"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )
        source = next(iter(index[(1, "17")].values()))
        cell = source["bbox"]
        inside = [cell[0] + 5, cell[1] + 3, cell[2] - 5, cell[3] - 3]
        line = {
            "text": "Compound 17",
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        for axis in range(4):
            for slack, accepted in ((0.8, True), (1.01, False)):
                box = list(inside)
                box[axis] = cell[axis] + (slack if axis >= 2 else -slack)
                with self.subTest(axis=axis, slack=slack):
                    reference = caption_label_reference({**line, "bbox": box}, 1, index)
                    self.assertEqual(reference is not None, accepted)
        outside = [inside[0], cell[3] + 0.1, inside[2], cell[3] + 0.9]
        self.assertIsNone(caption_label_reference({**line, "bbox": outside}, 1, index))
        ambiguous = copy.deepcopy(index)
        ambiguous[(1, "17")]["f" * 64] = {**source, "source_key": "f" * 64}
        self.assertIsNone(
            caption_label_reference({**line, "bbox": inside}, 1, ambiguous)
        )


if __name__ == "__main__":
    unittest.main()
