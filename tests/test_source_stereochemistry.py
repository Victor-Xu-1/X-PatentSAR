"""Source-bond conflicts must not pass syntactic OCSR quality control."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from patent_sar_extractor.core.ocsr import smiles_converter as converter_module
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import (
    observe_stereo_symbols,
    source_checked_qc,
)
from patent_sar_extractor.core.ocsr.stereo_gate import stereo_record_error


def wave_image(path: Path) -> None:
    canvas = Image.new("RGB", (200, 100), "white")
    points = [(20 + i, 50 + 3 * math.sin(i * math.pi / 5)) for i in range(61)]
    ImageDraw.Draw(canvas).line(points, fill="black", width=2)
    canvas.save(path)


class SourceStereochemistryTests(unittest.TestCase):
    def converter(self, raw: str, *, retry: bool = False, cache: str = ""):
        calls = []

        class ObservedEngine:
            def __init__(self, **_kwargs):
                pass

            def runtime_identity(self):
                return {"fingerprint": "a" * 64}

            def predict(self, image, timeout=60):
                calls.append(image)
                return {
                    "status": "success",
                    "raw_smiles": raw,
                    "model_fingerprint": "a" * 64,
                }

        with patch.dict(converter_module.ENGINE_MAP, {"decimer": ObservedEngine}):
            result = converter_module.SmilesConverter(
                ["decimer"],
                [],
                preprocess=False,
                retry_normalization=retry,
                cache_path=cache,
            )
        return result, calls

    def test_wave_cannot_be_promoted_to_a_defined_tetrahedral_center(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "source.png"
            wave_image(image)
            raw = "C[C@H](O)C(=O)O"
            converter, calls = self.converter(raw, retry=True)
            result = converter.convert_one(
                {"cpd": "arbitrary label", "image_path": str(image)},
                str(root / "inputs"),
            )
            self.assertEqual(result["OCSR_status"], "review_required")
            self.assertEqual(result["raw_smiles"], raw)
            self.assertEqual(result["engine_raw_smiles"], raw)
            self.assertEqual(
                len(calls), 1, "normalization cannot repair source semantics"
            )

    def test_cached_model_observation_must_pass_current_source_guard_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "source.png"
            wave_image(image)
            converter, calls = self.converter(
                "C[C@H](O)C(=O)O", cache=str(root / "raw.sqlite")
            )
            item = {"cpd": "unrelated ID", "image_path": str(image)}
            first, second = converter.convert_one(item), converter.convert_one(item)
            self.assertEqual(len(calls), 1)
            self.assertTrue(second["engine_attempts"][0]["from_cache"])
            self.assertEqual(first["OCSR_status"], "review_required")
            self.assertEqual(second["OCSR_status"], "review_required")

    def test_unknown_center_is_not_called_racemic_or_deduplicated_by_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.png"
            wave_image(path)
            converter, _ = self.converter("CC(O)C(=O)O")
            first = converter.convert_one(
                {"image_path": str(path), "cpd": "Fraction A"}
            )
            second = converter.convert_one(
                {"image_path": str(path), "cpd": "Fraction B"}
            )
            self.assertEqual(first["OCSR_status"], "success")
            self.assertEqual(second["OCSR_status"], "success")
            self.assertEqual(first["stereochemistry"]["status"], "unknown_preserved")
            self.assertNotIn("racemic", first["stereochemistry"])
            self.assertNotEqual(first["cpd_id"], second["cpd_id"])
            self.assertIsNone(stereo_record_error(first))

    def test_mixed_defined_and_unknown_centers_are_ambiguous_not_flipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.png"
            wave_image(path)
            converter, _ = self.converter("C[C@H](O)CC(Br)F")
            result = converter.convert_one({"image_path": str(path), "cpd": "anything"})
            self.assertEqual(result["OCSR_status"], "review_required")
            self.assertEqual(result["stereochemistry"]["status"], "ambiguous")
            self.assertEqual(result["raw_smiles"], "C[C@H](O)CC(Br)F")

    def test_missing_forged_or_changed_evidence_cannot_pass_formal_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.png"
            wave_image(path)
            converter, _ = self.converter("CC(O)C(=O)O")
            result = converter.convert_one({"image_path": str(path)})
            self.assertIsNone(stereo_record_error(result))
            missing = {**result, "stereochemistry": None}
            self.assertIsNotNone(stereo_record_error(missing))
            for changes in (
                {"version": 1},
                {"version": 2},
                {"version": 0},
                {"status": "no_unknown_detected"},
                {"absolute_configuration_verified": True},
                {"image_sha256": "b" * 64},
                {"unknown_bond_boxes": [[0, 0, 300, 200]]},
            ):
                with self.subTest(changes=changes):
                    changed = {
                        **result,
                        "stereochemistry": {**result["stereochemistry"], **changes},
                    }
                    self.assertIsNotNone(stereo_record_error(changed))


class SourceDrawingStyleTests(unittest.TestCase):
    def test_waves_are_observed_at_multiple_rotations_and_sizes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wave.png"
            wave_image(path)
            with Image.open(path) as wave:
                for angle in (0, 30, 60, 90, 120, 150):
                    for scale in (1, 2):
                        with self.subTest(angle=angle, scale=scale):
                            rotated = wave.rotate(angle, expand=True, fillcolor="white")
                            rotated = rotated.resize(
                                (rotated.width * scale, rotated.height * scale)
                            )
                            target = Path(temporary) / "variant.png"
                            rotated.save(target)
                            evidence = observe_stereo_symbols(target)
                            self.assertTrue(evidence["unknown_bond_boxes"])

    def test_planar_bonds_ring_and_wedges_are_not_wave_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            for kind in (
                "plain",
                "ring",
                "solid_wedge",
                "hashed_wedge",
                "crossed_double",
            ):
                with self.subTest(kind=kind):
                    image = Image.new("RGB", (200, 120), "white")
                    draw = ImageDraw.Draw(image)
                    if kind == "plain":
                        draw.line(
                            [(20, 60), (70, 30), (120, 60)], fill="black", width=2
                        )
                    elif kind == "ring":
                        draw.regular_polygon((70, 60, 30), 6, outline="black", width=2)
                    elif kind == "solid_wedge":
                        draw.polygon([(20, 60), (100, 50), (100, 70)], fill="black")
                    elif kind == "hashed_wedge":
                        for i in range(8):
                            draw.line(
                                [(20 + i * 10, 60 - i), (20 + i * 10, 60 + i)],
                                fill="black",
                                width=2,
                            )
                    else:
                        draw.line([(20, 55), (100, 65)], fill="black", width=2)
                        draw.line([(20, 65), (100, 55)], fill="black", width=2)
                    path = Path(temporary) / "diagram.png"
                    image.save(path)
                    self.assertEqual(
                        observe_stereo_symbols(path)["unknown_bond_boxes"], []
                    )

    def test_no_wave_hit_is_never_an_absolute_configuration_certificate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plain.png"
            Image.new("RGB", (100, 100), "white").save(path)
            result = source_checked_qc(
                qc_smiles("C[C@H](O)C(=O)O"), observe_stereo_symbols(path)
            )
            self.assertEqual(result["stereochemistry"]["status"], "no_unknown_detected")
            self.assertFalse(
                result["stereochemistry"]["absolute_configuration_verified"]
            )

    def test_unsupported_or_discarded_stereo_does_not_pass_syntax_only_qc(self):
        self.assertEqual(
            qc_smiles("C[C@H](C)O")["quality_flag"], "stereochemistry_not_retained"
        )
        self.assertEqual(
            qc_smiles("C[C@H](O)C[C@H](C)C")["quality_flag"],
            "stereochemistry_not_retained",
        )
        self.assertNotEqual(qc_smiles("F[Pt@SP1](Cl)(Br)I")["quality_flag"], "ok")
        self.assertEqual(
            qc_smiles("C/C=C(/C)C")["quality_flag"], "stereochemistry_not_retained"
        )
        self.assertEqual(qc_smiles("F/C=C/C=C/F")["quality_flag"], "ok")
        self.assertEqual(
            qc_smiles("C[C@H](O)F |o1:1|")["quality_flag"],
            "unsupported_smiles_metadata",
        )

    def test_unreadable_or_excessive_source_stops_before_loading_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.png"
            Image.new("RGB", (4, 4), "white").save(path)
            converter, calls = SourceStereochemistryTests().converter("CCO")
            result = converter.convert_one({"image_path": str(path)})
            self.assertEqual(result["OCSR_quality_flag"], "stereo_source_unavailable")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
