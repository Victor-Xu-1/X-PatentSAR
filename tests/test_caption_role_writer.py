"""Original catalogue roles through the actual binder, writer and formal reader."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.catalog_reader import (
    CatalogValidationError,
    read_catalog_entries,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.structure_binder import bind
from tests.test_caption_source_roles import catalog


class CaptionRoleWriterTests(unittest.TestCase):
    def execute(self, title="Table 47. Compounds", *, prefixed=False):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-caption-role-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        pdf, metadata = root / "original.pdf", root / "metadata.json"
        doc, structures, boxes = catalog(title, prefixed=prefixed)
        records = []
        with doc:
            doc.save(pdf)
            for index, (structure, box) in enumerate(
                zip(structures[1], boxes[1], strict=True)
            ):
                image = root / f"original-{index}.png"
                doc[0].get_pixmap(clip=box, alpha=False).save(image)
                records.append(
                    {
                        "structure_id": structure["id"],
                        "structure_index": index,
                        "page_no": 1,
                        "bbox_pdf": list(box),
                        "bbox": list(box),
                        "image_path": str(image),
                    }
                )
        metadata.write_text(
            json.dumps({"patent_number": "CONTROL-ROLE", "structures": records})
        )
        before = hashlib.sha256(pdf.read_bytes()).hexdigest()
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError(
                "Controlled native catalogue must not invoke OCR"
            ),
        ):
            result = bind(
                str(pdf),
                {"bind_workers": 1},
                str(root / "bindings"),
                structures_path=str(metadata),
            )
        self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), before)
        saved = json.loads(Path(result["output_files"]["json"]).read_text())
        self.assertEqual(saved["final_bindings"], result["final_bindings"])
        return saved, records

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
