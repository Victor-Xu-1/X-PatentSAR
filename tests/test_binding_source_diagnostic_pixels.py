"""Real source-pixel packets remain unresolved through the ordinary writer."""

import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import numpy as np
from PIL import Image

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.plot_reference_pixels import (
    observe_pixels,
    replay_pixels,
)
from patent_sar_extractor.core.source_cell_pixels import MAX_CELL_PIXELS
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.source_role_observations import (
    RoleObservationBuffer,
    _bounded_tree,
    validate_role_catalog,
)
from patent_sar_extractor.web.attempts import CheckpointCopy, VerifiedCheckpoint
from patent_sar_extractor.web.files import SafeFiles


class BindingDiagnosticPixelTests(unittest.TestCase):
    def diagnostic(self, packet, original):
        return {
            "version": 2,
            "kind": "binding_proposal",
            "status": "unresolved",
            "reason": "unproved_original_binding",
            "page_no": 1,
            "cpd": "Example 09A",
            "structure_id": "generated-structure",
            "proposal": {"original_pixel_context": packet},
            "original_pdf_sha256": original,
        }

    def source(self):
        # Independent generated source, never a private patent or model request.
        bits = np.random.default_rng(71).integers(0, 2, (400, 400), dtype=np.uint8)
        rgb = np.repeat((bits * 255)[:, :, None], 3, axis=2)
        png = io.BytesIO()
        Image.fromarray(rgb).save(png, format="PNG")
        bounds = [20, 20, 92, 92]
        with fitz.open() as document:
            page = document.new_page(width=160, height=160)
            page.insert_image(fitz.Rect(bounds), stream=png.getvalue())
            original = document.tobytes()
        with fitz.open(stream=original, filetype="pdf") as document:
            packet = observe_pixels(document[0], bounds, MAX_CELL_PIXELS)
            self.assertIsNotNone(packet)
            self.assertTrue(any(len(r["mask_hex"]) > 10000 for r in packet["readings"]))
            for reading in packet["readings"]:
                replay_pixels(document[0], bounds, reading)
        return packet, hashlib.sha256(original).hexdigest()

    def test_native_large_pixel_packet_survives_rejected_writer_and_reader(self):
        pixels, original = self.source()
        proposal = {
            "cpd": "Example 09A",
            "structure_id": "generated-structure",
            "page_no": 1,
            "binding_rule": "original_caption_cell",
            "exact_caption_evidence": {
                "bbox": [20, 20, 92, 92],
                "page_no": 1,
                "ownership": {"direction": None},
                "observations": [
                    {
                        "method": "cell_ocr_400dpi",
                        "raw_text": "Example 09A",
                        "confidence": 0.5,
                    }
                ],
            },
            "original_pixel_context": pixels,
        }
        with tempfile.TemporaryDirectory(
            prefix="controlled-diagnostic-pixels-"
        ) as folder:
            payload = write_binding_result(
                Path(folder),
                patent_id="CONTROLLED",
                bindings=[],
                catalog_bindings=[proposal],
                detected_style="original_cell_caption_heading",
                include_intermediates=False,
                total_structures=1,
                total_compound_blocks=0,
                table_pages=[0],
                table_covered_count=0,
                no_binding=[],
                unbound_pages=[],
                original_pdf_sha256=original,
            )
        self.assertEqual(payload["compound_catalog"]["entries"], [])
        catalog = payload["source_role_observations"]
        validate_role_catalog(catalog, original_pdf_sha256=original)
        observed = next(iter(catalog.values()))
        self.assertEqual(observed["status"], "unresolved")
        self.assertEqual(observed["proposal"]["original_pixel_context"], pixels)
        # Saving bytes or clearing issue flags must not qualify a rejected source.
        payload["source_issues"] = []
        payload["strict_coverage"]["unresolved_sources"] = []
        issues = reference_issues(payload, [], required=True)
        self.assertEqual([i["reason"] for i in issues], ["unproved_original_binding"])
        self.assertEqual(issues[0]["structure_id"], "generated-structure")

    def test_literal_roundtrip_checkpoint_identity_and_source_checks_remain(self):
        pixels, original = self.source()
        observation = self.diagnostic(pixels, original)
        buffer = RoleObservationBuffer()
        buffer.extend([observation, copy.deepcopy(observation)])
        self.assertEqual(len(buffer), 1)
        catalog = {proof_id(observation): next(iter(buffer))}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = {"source_role_observations": catalog}
            write_json_atomic(root / "retained.json", payload, shared=True)
            copier = CheckpointCopy(root, root / "copied")
            copier.checkpoint(
                VerifiedCheckpoint(
                    "bind",
                    "retained.json",
                    payload,
                    {"fingerprint": {"params": {}, "dependency_sha256": {}}},
                )
            )
            transported = SafeFiles(copier.target).json("retained.json")
        self.assertEqual(transported, payload)
        self.assertEqual(json.loads(json.dumps(catalog)), catalog)
        validate_role_catalog(catalog, original_pdf_sha256=original)
        with self.assertRaisesRegex(ValueError, "document"):
            validate_role_catalog(catalog, original_pdf_sha256="0" * 64)
        changed = copy.deepcopy(catalog)
        next(iter(changed.values()))["proposal"]["original_pixel_context"]["readings"][
            0
        ]["pixel_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_role_catalog(changed)

    def test_arbitrary_text_and_partial_or_foreign_packet_cannot_borrow_mask_cap(self):
        pixels, original = self.source()
        mask = max((reading["mask_hex"] for reading in pixels["readings"]), key=len)
        invalid = [
            {"mask_hex": mask},
            {**pixels, "unexpected": True},
            {**pixels, "readings": list(reversed(pixels["readings"]))},
        ]
        for packet in invalid:
            with (
                self.subTest(keys=tuple(packet)),
                self.assertRaisesRegex(ValueError, "budget"),
            ):
                RoleObservationBuffer().extend([self.diagnostic(packet, original)])
        aliased = self.diagnostic(pixels, original)
        aliased["proposal"]["raw_text"] = mask  # Same string object, not a mask owner.
        with self.assertRaisesRegex(
            ValueError, r"proposal/raw_text \([0-9]+ characters\)"
        ):
            RoleObservationBuffer().extend([aliased])
        with self.assertRaisesRegex(ValueError, "budget"):
            _bounded_tree({"pixels": pixels}, coordinate_tuples=True)

    def test_corrupt_compression_window_shape_and_pixel_bounds_cannot_escape(self):
        pixels, original = self.source()
        mutations = []
        extra_stream = copy.deepcopy(pixels)
        extra_stream["readings"][0]["mask_hex"] += "00"
        mutations.append(extra_stream)
        wrong_shape = copy.deepcopy(pixels)
        wrong_shape["readings"][0]["shape"][0] += 1
        mutations.append(wrong_shape)
        too_many_pixels = copy.deepcopy(pixels)
        too_many_pixels["readings"][0]["shape"] = [3000, 3000, 3]
        mutations.append(too_many_pixels)
        wrong_window = copy.deepcopy(pixels)
        wrong_window["readings"][0]["source_window"]["read_bounds"][2] -= 1
        mutations.append(wrong_window)
        wrong_dpi = copy.deepcopy(pixels)
        wrong_dpi["readings"][0]["dpi"] = 200
        mutations.append(wrong_dpi)
        for index, packet in enumerate(mutations):
            with (
                self.subTest(index=index),
                self.assertRaisesRegex(ValueError, "budget"),
            ):
                RoleObservationBuffer().extend([self.diagnostic(packet, original)])

    def test_single_view_historical_pixels_keep_the_same_literal_identity(self):
        pixels, original = self.source()
        reading = copy.deepcopy(pixels["readings"][0])
        reading.pop("source_window")
        height, width, _channels = reading["shape"]
        packet = {
            "bbox": [0, 0, 3 + width * 72 / 400, 2.4 + height * 72 / 400],
            "readings": [reading],
        }
        observation = self.diagnostic(packet, original)
        buffer = RoleObservationBuffer()
        buffer.extend([observation])
        self.assertEqual(next(iter(buffer)), observation)
        self.assertEqual(proof_id(next(iter(buffer))), proof_id(observation))

    def test_region_aggregate_attempt_array_and_scalar_budgets_are_unchanged(self):
        pixels, original = self.source()
        observation = self.diagnostic(pixels, original)
        oversized = copy.deepcopy(observation)
        oversized["proposal"]["raw_lines"] = ["x" * 4096] * 256
        with self.assertRaisesRegex(ValueError, "bounded region limit"):
            RoleObservationBuffer().extend([oversized])
        with (
            patch(
                "patent_sar_extractor.core.source_role_observations.MAX_ROLE_CATALOG_BYTES",
                128,
            ),
            self.assertRaisesRegex(ValueError, "catalog.*byte budget"),
        ):
            RoleObservationBuffer().extend([observation])
        with (
            patch(
                "patent_sar_extractor.core.source_role_observations.MAX_ROLE_ATTEMPTS", 1
            ),
            self.assertRaisesRegex(ValueError, "inventory"),
        ):
            RoleObservationBuffer().extend([observation, observation])
        for extra in ([0] * 4097, float("nan"), 1 << 65):
            invalid = copy.deepcopy(observation)
            invalid["proposal"]["extra"] = extra
            with (
                self.subTest(kind=type(extra).__name__),
                self.assertRaisesRegex(ValueError, "budget"),
            ):
                RoleObservationBuffer().extend([invalid])
