"""Actual pixels: no guessed glyph erasure and no cleanup of source stereo."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import numpy as np
from PIL import Image, ImageDraw

from patent_sar_extractor.application.smiles_policy import _smiles_acceptance_errors
from patent_sar_extractor.core.ocsr.label_mask import MAX_BYTES, source_geometry
from patent_sar_extractor.core.ocsr.run_smiles import (
    resolve_image_paths,
    validate_strict_smiles_results,
)
from patent_sar_extractor.core.ocsr.smiles_converter import (
    SmilesConverter,
    _mask_visible_label_for_ocsr,
)
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import source_checked_qc
from patent_sar_extractor.core.ocsr.stereo_gate import validate_stereo_record
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.recognition import recognition_status


class OCSRLabelPreservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.image = self.root / "original.png"

    def drawing(self, lower="NH2"):
        image = Image.new("RGB", (260, 120), "white")
        draw = ImageDraw.Draw(image)
        draw.line([(30, 30), (80, 18), (130, 30), (185, 18)], fill="black", width=3)
        draw.text((120, 84), lower, fill="black")
        image.save(self.image)
        return {
            "cpd": "Compound 38",
            "structure_id": "source-a",
            "page_no": 1,
            "image_path": str(self.image),
            "visible_label": "38",
        }

    def test_an_isolated_atom_annotation_is_not_a_compound_caption(self):
        item = self.drawing()
        original = self.image.read_bytes()
        output, info = _mask_visible_label_for_ocsr(
            str(self.image), item, str(self.root)
        )
        self.assertEqual(output, str(self.image))
        self.assertFalse(info.get("ocsr_label_masked"))
        self.assertEqual(self.image.read_bytes(), original)

    def test_a_real_label_without_original_position_proof_is_not_erased(self):
        item = self.drawing("38")
        output, info = _mask_visible_label_for_ocsr(
            str(self.image), item, str(self.root)
        )
        self.assertEqual(output, str(self.image))
        self.assertFalse(info.get("ocsr_label_masked"))

    def test_preparation_inspects_the_actual_original_source(self):
        item = self.drawing()
        converter = SmilesConverter(
            engines=[], fallback_engines=[], cache_path="", preprocess=False
        )
        prepared = converter._prepare_input(item, str(self.root))
        expected = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.assertTrue(prepared["ready"])
        self.assertEqual(prepared["result"]["ocsr_original_input"], str(self.image))
        self.assertEqual(prepared["image_hash"], expected)
        self.assertEqual(prepared["stereo_evidence"]["image_sha256"], expected)

    def proven(self, label="38"):
        item = self.drawing(label)
        item["cpd"] = f"Compound {label}"
        item["visible_label"] = label
        with Image.open(self.image) as image:
            bounds = ImageDraw.Draw(image).textbbox((120, 84), label)
        record = {
            "image_path": str(self.image),
            "structure_id": "source-a",
            "page_no": 1,
            "bbox_pdf": [0, 0, 260, 120],
            "bbox": [0, 0, 260, 120],
        }
        item["_ocsr_source_geometry"] = source_geometry(record, str(self.image))
        item["exact_caption_evidence"] = {
            "page_no": 1,
            "bbox": list(bounds),
            "observations": [{"method": "native_cell", "text": f"Compound {label}"}],
        }
        return item

    def test_only_the_proved_caption_pixels_change_and_original_bytes_survive(self):
        for label in ("38", "123AB", "I-001ABC"):
            with self.subTest(label=label):
                item = self.proven(label)
                original = self.image.read_bytes()
                output, info = _mask_visible_label_for_ocsr(
                    str(self.image), item, str(self.root)
                )
                self.assertNotEqual(output, str(self.image))
                self.assertTrue(info["ocsr_label_masked"])
                self.assertEqual(info["ocsr_label_mask_label"], label)
                self.assertEqual(self.image.read_bytes(), original)
                with Image.open(self.image) as source, Image.open(output) as masked:
                    changed = np.any(np.asarray(source) != np.asarray(masked), axis=2)
                x0, y0, x1, y1 = info["ocsr_label_mask_bbox"]
                self.assertTrue(changed[y0:y1, x0:x1].any())
                changed[y0:y1, x0:x1] = False
                self.assertFalse(changed.any())

    def test_masked_model_input_never_replaces_source_hash_or_stereo_crop(self):
        item = self.proven()
        original = hashlib.sha256(self.image.read_bytes()).hexdigest()
        converter = SmilesConverter(
            engines=[], fallback_engines=[], cache_path="", preprocess=False
        )
        prepared = converter._prepare_input(item, str(self.root))
        self.assertTrue(prepared["ready"])
        self.assertNotEqual(prepared["working_image"], str(self.image))
        self.assertEqual(prepared["result"]["ocsr_original_input"], str(self.image))
        self.assertEqual(prepared["image_hash"], original)
        self.assertEqual(prepared["stereo_evidence"]["image_sha256"], original)

    def test_foreign_stale_ambiguous_or_unmapped_caption_never_selects_a_mask(self):
        original = self.proven()
        mutations = (
            ("_ocsr_source_geometry", "image_sha256", "b" * 64),
            ("_ocsr_source_geometry", "page_no", 2),
            ("_ocsr_source_geometry", "page_no", True),
            ("_ocsr_source_geometry", "structure_id", "foreign"),
            ("_ocsr_source_geometry", "image_size", [260.0, 120.0]),
            ("_ocsr_source_geometry", "bbox", [0, 0, 260, 200]),
            ("_ocsr_source_geometry", "bbox", [0, 0, 1e-320, 1e-320]),
            ("_ocsr_source_geometry", "bbox", [0, 0, 1e308, 1e308]),
            ("_ocsr_source_geometry", "bbox", [0, 0, float("nan"), 120]),
            ("exact_caption_evidence", "page_no", 2),
            ("exact_caption_evidence", "page_no", True),
            ("exact_caption_evidence", "bbox", [0, 0, 500, 120]),
            (
                "exact_caption_evidence",
                "observations",
                [{"method": "native_cell", "text": "Compound 39"}],
            ),
        )
        for field, key, value in mutations:
            with self.subTest(field=field, key=key, value=value):
                item = copy.deepcopy(original)
                item[field][key] = value
                output, info = _mask_visible_label_for_ocsr(
                    str(self.image), item, str(self.root)
                )
                self.assertEqual(output, str(self.image))
                self.assertFalse(info.get("ocsr_label_masked"))

    def test_a_bond_touching_the_caption_rectangle_cannot_be_erased(self):
        item = self.proven()
        bounds = item["exact_caption_evidence"]["bbox"]
        with Image.open(self.image) as image:
            ImageDraw.Draw(image).line(
                [(bounds[0] - 8, bounds[1] + 3), (bounds[0] + 5, bounds[1] + 3)],
                fill="black",
                width=2,
            )
            image.save(self.image)
        item["_ocsr_source_geometry"]["image_sha256"] = hashlib.sha256(
            self.image.read_bytes()
        ).hexdigest()
        output, info = _mask_visible_label_for_ocsr(
            str(self.image), item, str(self.root)
        )
        self.assertEqual(output, str(self.image))
        self.assertFalse(info.get("ocsr_label_masked"))

    def test_actual_native_pdf_caption_reaches_preparation_through_metadata(self):
        self.check_native_caption_preparation("Compound 123AB", masked=True)

    def test_native_literal_elution_note_uses_the_same_caption_preparation_authority(
        self,
    ):
        self.check_native_caption_preparation(
            "Compound 123AB *first eluting isomer", masked=True
        )

    def test_native_unknown_annotation_cannot_be_masked_by_agreeing_values(self):
        self.check_native_caption_preparation(
            "Compound 123AB third unknown annotation", masked=False
        )

    def check_native_caption_preparation(self, text, *, masked):
        doc = fitz.open()
        self.addCleanup(doc.close)
        page = doc.new_page(width=500, height=120)
        page.draw_line((30, 30), (80, 18))
        page.draw_line((80, 18), (130, 30))
        page.insert_text((80, 94), text, fontsize=12)
        caption = page.get_text("blocks")[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
        pixmap.save(str(self.image))
        metadata = self.root / "structures"
        metadata.mkdir()
        record = {
            "structure_id": "source-a",
            "page_no": 1,
            "image_path": str(self.image),
            "bbox": [0, 0, pixmap.width, pixmap.height],
            "bbox_pdf": [0, 0, pixmap.width * 72 / 150, pixmap.height * 72 / 150],
        }
        (metadata / "metadata.json").write_text(json.dumps({"structures": [record]}))
        item = {
            "cpd": "Example 123AB",
            "structure_id": "source-a",
            "page_no": 1,
            "image_path": str(self.image),
            "visible_label": "123AB",
            "exact_caption_evidence": {
                "page_no": 1,
                "bbox": list(caption[:4]),
                "observations": [{"method": "native_cell", "text": caption[4].strip()}],
            },
        }
        resolved = resolve_image_paths([item], str(self.root / "structure_bindings"))[0]
        self.assertIn("_ocsr_source_geometry", resolved)
        before = self.image.read_bytes()
        output, info = _mask_visible_label_for_ocsr(
            str(self.image), resolved, str(self.root)
        )
        self.assertEqual(output != str(self.image), masked)
        self.assertEqual(bool(info.get("ocsr_label_masked")), masked)
        self.assertEqual(self.image.read_bytes(), before)

    def test_serialized_mask_cannot_hide_legacy_flag_or_source_projection_changes(self):
        item = self.proven()
        converter = SmilesConverter(
            engines=[], fallback_engines=[], cache_path="", preprocess=False
        )
        prepared = converter._prepare_input(item, str(self.root))
        record = {
            **prepared["result"],
            **source_checked_qc(qc_smiles("CCO"), prepared["stereo_evidence"]),
            "raw_smiles": "CCO",
        }
        self.assertEqual(
            validate_stereo_record(record)["image_sha256"], record["image_hash"]
        )
        for key, value in (
            ("ocsr_label_masked", False),
            ("OCSR_preparation_version", True),
            ("ocsr_original_input", record["ocsr_structure_image"]),
            ("ocsr_label_mask_bbox", [0, 0, 260, 120]),
            ("ocsr_label_mask_label", "39"),
            ("ocsr_label_mask_proof", {}),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(record)
                changed[key] = value
                with self.assertRaises(ValueError):
                    validate_stereo_record(changed)

    def recognition_record(self, item):
        converter = SmilesConverter(
            engines=[], fallback_engines=[], cache_path="", preprocess=False
        )
        prepared = converter._prepare_input(item, str(self.root))
        return {
            **prepared["result"],
            **source_checked_qc(qc_smiles("CCO"), prepared["stereo_evidence"]),
            "raw_smiles": "CCO",
            "OCSR_quality_flag": "ok",
            "OCSR_status": "success",
            "model_fingerprint": "a" * 64,
        }

    def test_self_consistent_moved_proof_cannot_outvote_the_original_binding(self):
        binding = self.proven()
        record = self.recognition_record(binding)
        changed = copy.deepcopy(record)
        changed["ocsr_label_mask_proof"]["caption"]["bbox"] = [120, 50, 134, 60]
        changed["ocsr_label_mask_bbox"] = [119, 49, 135, 61]
        # This is internally consistent but disagrees with original saved source.
        validate_stereo_record(changed)
        self.assertTrue(validate_strict_smiles_results([binding], [changed]))
        self.assertTrue(
            _smiles_acceptance_errors([changed], {"final_bindings": [binding]})
        )

    def test_historical_cleanup_is_readable_but_never_current_chemistry(self):
        record = self.recognition_record(self.proven())
        record.pop("OCSR_preparation_version")
        record.pop("ocsr_label_mask_proof")
        record["ocsr_original_input"] = record["ocsr_structure_image"]
        before = copy.deepcopy(record)
        result = recognition_status(record, current=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("stereochemistry", result)
        self.assertEqual(record, before)

    def test_current_cleanup_corruption_is_not_disguised_as_legacy(self):
        record = self.recognition_record(self.proven())
        record["ocsr_label_mask_proof"] = {}
        with self.assertRaises(WebError):
            recognition_status(record, current=True)

    def test_changed_crop_frame_cannot_outvote_current_metadata(self):
        binding = self.proven()
        record = self.recognition_record(binding)
        binding.pop("_ocsr_source_geometry")
        source = {
            "structure_id": "source-a",
            "page_no": 1,
            "bbox_pdf": [0, 0, 260, 120],
        }
        validate_stereo_record(record, binding, source)
        with self.assertRaises(ValueError):
            validate_stereo_record(
                record, binding, {**source, "bbox_pdf": [0, 0, 260, 200]}
            )
        self.assertEqual(
            recognition_status(
                record, current=True, binding=binding, source_record=source
            )["status"],
            "valid",
        )
        with self.assertRaises(WebError):
            recognition_status(
                record,
                current=True,
                binding=binding,
                source_record={**source, "structure_id": "foreign"},
            )

    def test_rotated_original_page_projects_caption_without_rotating_twice(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), fitz.open() as doc:
                page = doc.new_page(width=260, height=120)
                page.draw_line((30, 30), (90, 18))
                page.insert_text((80, 94), "Compound I-073AB", fontsize=12)
                page.set_rotation(rotation)
                caption = page.get_text("blocks")[0]
                bounds = fitz.Rect(caption[:4]) * page.rotation_matrix
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False
                )
                pixmap.save(str(self.image))
                frame = source_geometry(
                    {
                        "image_path": str(self.image),
                        "page_no": 1,
                        "structure_id": "source-a",
                        "bbox": [0, 0, pixmap.width, pixmap.height],
                        "bbox_pdf": [
                            0,
                            0,
                            pixmap.width * 72 / 150,
                            pixmap.height * 72 / 150,
                        ],
                    },
                    str(self.image),
                )
                item = {
                    "cpd": "Example I-073AB",
                    "structure_id": "source-a",
                    "page_no": 1,
                    "_ocsr_source_geometry": frame,
                    "exact_caption_evidence": {
                        "page_no": 1,
                        "bbox": list(bounds),
                        "observations": [
                            {"method": "native_cell", "text": caption[4].strip()}
                        ],
                    },
                }
                before = self.image.read_bytes()
                output, info = _mask_visible_label_for_ocsr(
                    str(self.image), item, str(self.root)
                )
                self.assertNotEqual(output, str(self.image))
                self.assertTrue(info["ocsr_label_masked"])
                self.assertEqual(self.image.read_bytes(), before)
                with Image.open(self.image) as source, Image.open(output) as masked:
                    changed = np.any(np.asarray(source) != np.asarray(masked), axis=2)
                x0, y0, x1, y1 = info["ocsr_label_mask_bbox"]
                changed[y0:y1, x0:x1] = False
                self.assertFalse(changed.any())

    def test_source_bounds_and_atomic_failure_preserve_previous_derivative(self):
        item = self.proven()
        output, _ = _mask_visible_label_for_ocsr(str(self.image), item, str(self.root))
        previous = Path(output).read_bytes()
        with (
            patch(
                "patent_sar_extractor.core.ocsr.image_preprocess.os.replace",
                side_effect=OSError("controlled atomic publication failure"),
            ),
            self.assertRaises(OSError),
        ):
            _mask_visible_label_for_ocsr(str(self.image), item, str(self.root))
        self.assertEqual(Path(output).read_bytes(), previous)
        self.assertEqual(list(Path(output).parent.glob(".prepare-*.png")), [])
        self.image.write_bytes(b"x" * (MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "byte bound"):
            _mask_visible_label_for_ocsr(str(self.image), item, str(self.root))
        Image.new("1", (3000, 3000), 1).save(self.image)
        with self.assertRaisesRegex(ValueError, "pixel bound"):
            _mask_visible_label_for_ocsr(str(self.image), item, str(self.root))
