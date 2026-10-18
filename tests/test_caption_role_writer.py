"""Original catalogue roles through the actual binder, writer and formal reader."""

import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.catalog_reader import (
    CatalogValidationError,
    read_catalog_entries,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.core.table_geometry import (
    detect_ruled_table_regions,
    page_tokens,
)
from tests.test_caption_nomination_forms import changed_caption_hints
from tests.test_caption_page_boundary import below_pages
from tests.test_caption_role_raster import raster_catalog
from tests.test_caption_source_roles import catalog
from tests.test_parallel_caption_boundary import parallel_catalogues


class CaptionRoleWriterTests(unittest.TestCase):
    def execute(self, title="Table 47. Compounds", *, prefixed=False):
        return self.execute_document(*catalog(title, prefixed=prefixed))

    def execute_document(
        self, doc, structures, boxes, *, native=True, token_reader=None
    ):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-caption-role-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        pdf, metadata = root / "original.pdf", root / "metadata.json"
        records = []
        with doc:
            doc.save(pdf)
            for page_no in sorted(structures):
                for structure, box in zip(
                    structures[page_no], boxes[page_no], strict=True
                ):
                    index = len(records)
                    image = root / f"original-{index}.png"
                    doc[page_no - 1].get_pixmap(clip=box, alpha=False).save(image)
                    records.append(
                        {
                            "structure_id": structure["id"],
                            "structure_index": index,
                            "page_no": page_no,
                            "bbox_pdf": list(box),
                            "bbox": list(box),
                            "image_path": str(image),
                        }
                    )
        metadata.write_text(
            json.dumps({"patent_number": "CONTROL-ROLE", "structures": records})
        )
        before = hashlib.sha256(pdf.read_bytes()).hexdigest()
        native_guard = patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError(
                "Controlled native catalogue must not invoke OCR"
            ),
        )
        source_reader = (
            patch(
                "patent_sar_extractor.core.binding_spatial.page_tokens",
                side_effect=token_reader,
            )
            if token_reader
            else nullcontext()
        )
        with native_guard if native else nullcontext(), source_reader:
            result = bind(
                str(pdf),
                {"bind_workers": 1},
                str(root / "bindings"),
                structures_path=str(metadata),
            )
        self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), before)
        saved = load_json(Path(result["output_files"]["json"]), None)
        self.assertEqual(saved["final_bindings"], result["final_bindings"])
        return saved, records

    def test_page_hint_authority_is_preserved_through_writer_and_catalogue(self):
        for confidence in (0.01, 0.99):
            with self.subTest(confidence=confidence):

                def source_reader(page, _confidence=confidence, **kwargs):
                    tokens = page_tokens(page, **kwargs)
                    grid = detect_ruled_table_regions(page, dpi=240)[0]
                    return changed_caption_hints(
                        tokens, grid, "Compound I-099Z", _confidence
                    )

                payload, records = self.execute_document(
                    *raster_catalog("Table 47. Structures", prefixed=True),
                    native=False,
                    token_reader=source_reader,
                )
                if confidence == 0.99:
                    self.assertEqual(payload["final_bindings"], [])
                    self.assertTrue(payload["source_issues"])
                    self.assertTrue(coverage_errors(payload))
                    continue
                entries, _ = read_catalog_entries(
                    payload, {record["structure_id"] for record in records}
                )
                self.assertEqual(
                    {entry["cpd"] for entry in entries},
                    {"Compound I-004A", "Compound I-009B"},
                )
                self.assertEqual(payload["source_issues"], [])
                self.assertEqual(coverage_errors(payload), [])

    def test_prefixed_captions_with_unknown_title_role_keep_one_frame_authority(self):
        payload, records = self.execute_document(
            *raster_catalog("Table 47. Structures", prefixed=True), native=False
        )
        entries, _ = read_catalog_entries(
            payload, {record["structure_id"] for record in records}
        )
        self.assertEqual(
            {entry["cpd"] for entry in entries},
            {"Compound I-004A", "Compound I-009B"},
        )
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])

    def test_actual_raster_caption_frame_survives_writer_and_strict_saved_reader(self):
        payload, records = self.execute_document(
            *raster_catalog(prefixed=True, labels=("42", "581"), label_fontname="hebo"),
            native=False,
        )
        entries, _ = read_catalog_entries(
            payload, {record["structure_id"] for record in records}
        )
        self.assertEqual(
            {entry["cpd"] for entry in entries}, {"Compound 42", "Compound 581"}
        )
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        for entry in entries:
            readings = entry["exact_caption_evidence"]["observations"]
            self.assertTrue(
                any(
                    reading.get("physical_caption_line", {}).get("version") == 3
                    for reading in readings
                )
            )
        changed = copy.deepcopy(payload)
        reading = next(
            reading
            for reading in changed["compound_catalog"]["entries"][0][
                "exact_caption_evidence"
            ]["observations"]
            if "physical_caption_line" in reading
        )
        reading["physical_caption_line"]["version"] = 1
        with self.assertRaises(CatalogValidationError):
            read_catalog_entries(changed)

    def test_actual_binder_writer_and_saved_catalogue_keep_later_page_captions(self):
        doc, structures, boxes, _grids = below_pages()
        payload, records = self.execute_document(doc, structures, boxes)
        self.assertEqual(
            len(payload["final_bindings"]),
            6,
            [
                (issue.get("cpd"), issue.get("page_no"), issue.get("reason"))
                for issue in payload["source_issues"]
            ],
        )
        self.assertEqual(payload["source_issues"], [])
        entries, _aliases = read_catalog_entries(
            payload, {r["structure_id"] for r in records}
        )
        self.assertEqual(reference_issues(payload, entries), [])
        self.assertEqual(coverage_errors(payload), [])
        cross = next(row for row in entries if row["cpd"] == "Compound 7E")
        self.assertEqual(cross["page_no"], 1)
        self.assertEqual(cross["exact_caption_evidence"]["page_no"], 2)
        self.assertTrue(all(Path(record["image_path"]).is_file() for record in records))

    def test_actual_binder_and_writer_publish_original_bare_ids_with_role_proof(self):
        payload, records = self.execute()
        self.assertEqual(
            [b["cpd"] for b in payload["final_bindings"]],
            ["Compound I-004A", "Compound I-009B"],
        )
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        before = copy.deepcopy(payload)
        entries, _aliases = read_catalog_entries(
            payload, {r["structure_id"] for r in records}
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(payload, before)
        changed = copy.deepcopy(payload)
        owner = changed["compound_catalog"]["entries"][0]["exact_caption_evidence"][
            "ownership"
        ]
        owner["caption_role"]["observations"] = []
        with self.assertRaises(CatalogValidationError):
            read_catalog_entries(changed)

    def test_actual_binder_writer_and_saved_consumers_keep_parallel_cross_page_sources(
        self,
    ):
        doc, structures, boxes, _grids = parallel_catalogues()
        payload, records = self.execute_document(doc, structures, boxes)
        self.assertEqual(len(payload["final_bindings"]), 12, payload["source_issues"])
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        entries, _aliases = read_catalog_entries(
            payload, {row["structure_id"] for row in records}
        )
        self.assertEqual(reference_issues(payload, entries), [])
        self.assertEqual(len(entries), 12)
        for label in ("Compound 7E", "Compound 97E"):
            row = next(entry for entry in entries if entry["cpd"] == label)
            self.assertEqual(row["page_no"], 1)
            self.assertEqual(row["exact_caption_evidence"]["page_no"], 2)

    def add_numbered_table(self, doc, structures, boxes, label="82"):
        page = doc[0]
        xs, ys = [50, 180, 310], [300, 325, 405]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        page.insert_text((50, 285), "Table 48. Compounds", fontsize=10)
        page.insert_text((65, 317), "Compound No.", fontsize=9)
        page.insert_text((195, 317), "Structure", fontsize=9)
        page.insert_text((65, 350), label, fontsize=9)
        box = (210, 340, 270, 380)
        structures[1].append(
            {
                "id": "numbered-82",
                "page_no": 1,
                **dict(zip(("x0", "y0", "x1", "y1"), box)),
            }
        )
        boxes[1].append(box)

    def test_numbered_table_on_same_page_cannot_hide_a_proved_caption_frame(self):
        doc, structures, boxes = catalog(prefixed=True)
        self.add_numbered_table(doc, structures, boxes)
        payload, records = self.execute_document(doc, structures, boxes)
        self.assertEqual(
            {row["cpd"] for row in payload["final_bindings"]},
            {"Compound I-004A", "Compound I-009B", "Compound 82"},
        )
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        entries, _ = read_catalog_entries(
            payload, {row["structure_id"] for row in records}
        )
        self.assertEqual(len(entries), 3)

    def test_same_original_id_in_competing_frames_is_not_silently_filtered(self):
        doc, structures, boxes = catalog(prefixed=True)
        self.add_numbered_table(doc, structures, boxes, label="I-004A")
        payload, records = self.execute_document(doc, structures, boxes)
        self.assertFalse(
            any(row["cpd"] == "Compound I-004A" for row in payload["final_bindings"])
        )
        self.assertTrue(
            any(
                issue.get("reason") == "ambiguous_compound_owner"
                for issue in payload["source_issues"]
            ),
            payload["source_issues"],
        )
        self.assertTrue(coverage_errors(payload))
        self.assertEqual(len(records), 3)
        self.assertTrue(all(Path(record["image_path"]).is_file() for record in records))

    def test_actual_binder_retains_nonfinal_source_sections_and_raw_assets(self):
        payload, records = self.execute("Table 47. Intermediates", prefixed=True)
        self.assertEqual(payload["final_bindings"], [])
        sections = [
            s
            for s in payload["source_sections"]
            if s["role"] == "nonfinal_caption_catalog"
        ]
        self.assertEqual(len(sections), 1)
        self.assertEqual(
            set(sections[0]["structure_ids"]), {r["structure_id"] for r in records}
        )
        self.assertTrue(all(Path(r["image_path"]).is_file() for r in records))
        for mutation in ("delete", "downgrade"):
            changed = copy.deepcopy(payload)
            if mutation == "delete":
                changed["source_sections"] = [
                    s
                    for s in changed["source_sections"]
                    if s["role"] != "nonfinal_caption_catalog"
                ]
            else:
                changed["source_reference_scope"]["version"] = 1
                del changed["source_reference_scope"]["caption_region_ids"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                reference_issues(changed, [])

    def test_native_multilingual_intermediate_titles_remain_nonfinal_after_saving(self):
        for label in ("中间体", "中間体", "中間體"):
            with self.subTest(label=label):
                payload, records = self.execute_document(
                    *catalog(
                        f"Table 47. {label}化合物", prefixed=True, fontname="china-t"
                    )
                )
                self.assertEqual(payload["final_bindings"], [])
                self.assertEqual(reference_issues(payload, []), [])
                self.assertTrue(coverage_errors(payload))
                self.assertTrue(all(Path(r["image_path"]).is_file() for r in records))
                sections = [
                    s
                    for s in payload["source_sections"]
                    if s["role"] == "nonfinal_caption_catalog"
                ]
                self.assertEqual(len(sections), 1)
                self.assertEqual(
                    set(sections[0]["structure_ids"]),
                    {r["structure_id"] for r in records},
                )

    def test_native_mixed_traditional_catalogue_does_not_exclude_its_final_category(
        self,
    ):
        payload, records = self.execute_document(
            *catalog("Table 47. 中間體及實施例", prefixed=True, fontname="china-t")
        )
        self.assertEqual(payload["final_bindings"], [])
        self.assertTrue(payload["source_issues"])
        self.assertTrue(coverage_errors(payload))
        self.assertFalse(
            any(
                s["role"] == "nonfinal_caption_catalog"
                for s in payload["source_sections"]
            )
        )
        self.assertTrue(all(Path(r["image_path"]).is_file() for r in records))

    def test_original_paragraph_prefix_cannot_hide_a_caption_catalogue_role(self):
        payload, records = self.execute(
            "[0042] Table 47. Intermediate compounds", prefixed=True
        )
        self.assertEqual(payload["final_bindings"], [])
        self.assertEqual(reference_issues(payload, []), [])
        self.assertEqual(
            coverage_errors(payload),
            ["No proved printed-ID structure is available for formal processing."],
        )
        self.assertTrue(all(Path(record["image_path"]).is_file() for record in records))

    def test_unknown_role_is_retained_as_incomplete_source_not_accepted_empty_data(
        self,
    ):
        payload, _records = self.execute("Table 47. Structures")
        self.assertEqual(payload["final_bindings"], [])
        self.assertTrue(payload["source_issues"])
        self.assertTrue(coverage_errors(payload))

    def test_mixed_role_never_becomes_a_complete_empty_terminal_catalog(self):
        payload, _records = self.execute(
            "Table 47. Compounds and intermediates", prefixed=True
        )
        self.assertEqual(payload["final_bindings"], [])
        self.assertFalse(
            any(
                s["role"] == "nonfinal_caption_catalog"
                for s in payload["source_sections"]
            )
        )
        self.assertTrue(payload["source_issues"])
        self.assertTrue(coverage_errors(payload))
