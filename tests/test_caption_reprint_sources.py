"""Proved caption reprints share the existing catalogue and recognition chain."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.catalog_reader import (
    CatalogValidationError,
    read_catalog_entries,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.structure_binder import bind
from tests.test_caption_source_roles import catalog


def numbered_catalog(title, *, labels, **_layout):
    document = fitz.open()
    page = document.new_page()
    xs, ys = [50, 200, 380], [100, 125, *(205 + 80 * i for i in range(len(labels)))]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    page.insert_text((50, 85), title, fontsize=10)
    page.insert_text((65, 117), "Compound No.", fontsize=9)
    page.insert_text((220, 117), "Structure", fontsize=9)
    structures, boxes = [], []
    for index, label in enumerate(labels):
        top = ys[index + 1]
        page.insert_text((70, top + 20), label, fontsize=9)
        box = (230, top + 15, 300, top + 50)
        page.draw_line((230, top + 27), (260, top + 15))
        page.draw_line((260, top + 15), (300, top + 27))
        boxes.append(box)
        structures.append(
            {
                "id": f"original-{index}",
                "page_no": 1,
                **dict(zip(("x0", "y0", "x1", "y1"), box)),
            }
        )
    return document, {1: structures}, {1: boxes}


class CaptionReprintSourcesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="caption-original-reprints-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def observe(
        self,
        second="Table 48. Selected compounds",
        *,
        novel=False,
        selected_first=False,
        single_column=False,
        styles=("caption", "caption"),
        raster=False,
    ):
        root = Path(tempfile.mkdtemp(prefix="source-", dir=self.root))
        source = root / "original.pdf"
        rows = []
        with fitz.open() as document:
            for number, title, labels in (
                (
                    1,
                    "Table 47. Selected compounds"
                    if selected_first
                    else "Table 47. Compounds",
                    ("53Q",) if single_column else ("53Q", "61R"),
                ),
                (
                    2,
                    second,
                    ("53Q", "53R")
                    if novel
                    else ("53Q",)
                    if single_column
                    else ("53Q", "61R"),
                ),
            ):
                factory = (
                    numbered_catalog if styles[number - 1] == "numbered" else catalog
                )
                original, structures, _boxes = factory(
                    title, prefixed=True, labels=labels
                )
                with original:
                    if raster:
                        pixels = original[0].get_pixmap(
                            matrix=fitz.Matrix(3, 3), alpha=False
                        )
                        page = document.new_page()
                        page.insert_image(page.rect, stream=pixels.tobytes("png"))
                    else:
                        document.insert_pdf(original)
                for index, diagram in enumerate(structures[1]):
                    bounds = [diagram[axis] for axis in ("x0", "y0", "x1", "y1")]
                    identity = f"source-{number}-{index}"
                    image = root / (identity + ".png")
                    document[number - 1].get_pixmap(clip=fitz.Rect(bounds)).save(image)
                    rows.append(
                        {
                            "structure_id": identity,
                            "structure_index": index,
                            "page_no": number,
                            "bbox_pdf": bounds,
                            "image_path": str(image),
                        }
                    )
            document.save(source)
        metadata = root / "structures.json"
        metadata.write_text(
            json.dumps({"patent_number": "CONTROLLED-REPRINT", "structures": rows})
        )
        result = bind(
            str(source),
            {"active_cpds": [], "structure_candidate_pages": [0, 1]},
            str(root / "bindings"),
            str(metadata),
        )
        saved = load_json(Path(result["output_files"]["json"]), None)
        self.assertIsInstance(saved, dict)
        self.assertEqual(saved["final_bindings"], result["final_bindings"])
        return saved

    def test_explicit_selected_caption_reprint_is_retained_and_scheduled(self):
        payload = self.observe()
        self.assertEqual(
            payload["source_issues"],
            [],
            {
                "issues": payload["source_issues"],
                "bindings": [
                    (row["cpd"], row["page_no"], row["binding_rule"])
                    for row in payload["final_bindings"]
                ],
                "sections": [
                    (row["role"], row.get("page_no"))
                    for row in payload["source_sections"]
                ],
            },
        )
        entries = payload["compound_catalog"]["entries"]
        self.assertEqual(
            [entry["cpd"] for entry in entries], ["Compound 53Q", "Compound 61R"]
        )
        self.assertTrue(all(len(entry["additional_sources"]) == 1 for entry in entries))
        self.assertEqual(payload["compound_catalog"]["source_observations"], 4)
        plan = recognition_inputs(payload)
        self.assertEqual(len(plan.formal), 2)
        self.assertEqual(len(plan.reprints), 2)
        self.assertEqual(
            {row["structure_id"] for row in plan.work_items},
            {"source-1-0", "source-1-1", "source-2-0", "source-2-1"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_single_column_original_catalogue_uses_the_same_complete_source_chain(self):
        payload = self.observe(single_column=True)
        self.assertEqual(payload["source_issues"], [])
        entries = payload["compound_catalog"]["entries"]
        self.assertEqual([entry["cpd"] for entry in entries], ["Compound 53Q"])
        self.assertEqual(len(entries[0]["additional_sources"]), 1)
        self.assertEqual(len(recognition_inputs(payload).work_items), 2)
        self.assertEqual(coverage_errors(payload), [])

    def test_numbered_and_caption_sources_share_one_selected_reprint_authority(self):
        for styles in (("numbered", "caption"), ("caption", "numbered")):
            with self.subTest(styles=styles):
                payload = self.observe(single_column=True, styles=styles)
                self.assertEqual(payload["source_issues"], [])
                self.assertEqual(payload["compound_catalog"]["numbered_compounds"], 1)
                self.assertEqual(payload["compound_catalog"]["source_observations"], 2)
                self.assertEqual(len(recognition_inputs(payload).work_items), 2)
                self.assertEqual(coverage_errors(payload), [])

    def test_scanned_single_column_sources_use_original_pixels_and_saved_replay(self):
        payload = self.observe(single_column=True, raster=True)
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(payload["compound_catalog"]["numbered_compounds"], 1)
        self.assertEqual(payload["compound_catalog"]["source_observations"], 2)
        self.assertEqual(len(recognition_inputs(payload).work_items), 2)
        self.assertEqual(coverage_errors(payload), [])

    def test_saved_selected_source_cannot_replace_the_complete_primary(self):
        payload = self.observe(single_column=True)
        entries, _aliases = read_catalog_entries(payload)
        self.assertEqual(len(entries), 1)
        original = copy.deepcopy(payload["compound_catalog"]["entries"][0])
        selected = original.pop("additional_sources")[0]
        promoted = {**selected, "additional_sources": [original]}
        payload["compound_catalog"]["entries"] = [promoted]
        payload["final_bindings"] = [promoted]
        with self.assertRaisesRegex(CatalogValidationError, "claim"):
            read_catalog_entries(payload)

    def test_competing_complete_caption_catalogues_are_not_merged(self):
        payload = self.observe(second="Table 48. Compounds")
        self.assertEqual(payload["final_bindings"], [])
        self.assertTrue(payload["source_issues"])
        conflicts = [
            issue
            for issue in payload["source_issues"]
            if issue["reason"] == "ambiguous_compound_owner"
        ]
        self.assertEqual(
            {issue["structure_id"] for issue in conflicts},
            {"source-1-0", "source-1-1", "source-2-0", "source-2-1"},
        )
        for issue in conflicts:
            observation = payload["source_role_observations"][
                issue["evidence"]["source_diagnostic"]
            ]
            self.assertEqual(
                observation["proposal"]["structure_id"], issue["structure_id"]
            )
            self.assertIn(
                "caption_role",
                observation["proposal"]["exact_caption_evidence"]["ownership"],
            )
            self.assertEqual(observation["status"], "unresolved")

    def test_selected_word_cannot_hide_novel_original_identifiers(self):
        payload = self.observe(novel=True)
        self.assertEqual(
            {row["cpd"] for row in payload["final_bindings"]},
            {"Compound 53R", "Compound 61R"},
        )
        self.assertTrue(payload["source_issues"])
        self.assertTrue(coverage_errors(payload))

    def test_two_selected_caption_tables_cannot_invent_a_complete_primary(self):
        payload = self.observe(selected_first=True)
        self.assertEqual(payload["final_bindings"], [])
        self.assertTrue(payload["source_issues"])

    def test_negated_or_mixed_selected_title_cannot_hide_competing_sources(self):
        for title in (
            "Table 48. Not selected compounds",
            "Table 48. Non-selected compounds",
            "Table 48. Selected and remaining compounds",
        ):
            with self.subTest(title=title):
                payload = self.observe(second=title)
                self.assertEqual([row["cpd"] for row in payload["final_bindings"]], [])
                self.assertTrue(payload["source_issues"])


if __name__ == "__main__":
    unittest.main()
