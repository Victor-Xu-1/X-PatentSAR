from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from patent_sar_extractor.core.ocsr import smiles_converter as converter_module
from patent_sar_extractor.core.ocsr.smiles_cache import (
    SmilesCache,
    compute_image_sha256,
)


class RawOCSRObservationTests(unittest.TestCase):
    def fixture(self, root):
        image = root / "original.png"
        canvas = Image.new("RGB", (160, 100), "white")
        ImageDraw.Draw(canvas).line(
            [(20, 25), (60, 60), (100, 25)], fill="black", width=2
        )
        canvas.save(image)
        return {"cpd": "Compound 1", "structure_id": "S0001", "image_path": str(image)}

    def converter(self, outputs, *, cache="", retry=False):
        calls = []

        class BoundaryEngine:
            def __init__(self, **kwargs):
                self.fingerprint = "a" * 64

            def runtime_identity(self):
                return {"fingerprint": self.fingerprint}

            def predict(self, image, timeout=60):
                calls.append(image)
                return {
                    "status": "success",
                    "raw_smiles": outputs[min(len(calls) - 1, len(outputs) - 1)],
                    "model_fingerprint": self.fingerprint,
                }

        with patch.dict(converter_module.ENGINE_MAP, {"decimer": BoundaryEngine}):
            converter = converter_module.SmilesConverter(
                ["decimer"],
                [],
                cache_path=cache,
                preprocess=False,
                retry_normalization=retry,
            )
        return converter, calls

    def test_legacy_clean_cache_has_no_raw_provenance_and_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = self.fixture(root)
            cache = root / "cache.sqlite"
            SmilesCache(str(cache)).save_result(
                compute_image_sha256(item["image_path"]),
                "decimer",
                {
                    "status": "success",
                    "raw_smiles": "CCCl",
                    "rdkit_valid": True,
                    "quality_flag": "ok",
                },
            )
            converter, calls = self.converter(["CC[Cu]"], cache=str(cache))
            result = converter.convert_one(item)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["raw_smiles"], "CC[Cu]")
            self.assertEqual(result["OCSR_status"], "review_required")
            self.assertTrue(result["engine_attempts"][0]["ignored_cached_precontract"])

    def test_exact_raw_observation_is_cached_without_repeated_model_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = self.fixture(root)
            converter, calls = self.converter(["CCO"], cache=str(root / "cache.sqlite"))
            first = converter.convert_one(item)
            second = converter.convert_one(item)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["raw_smiles"], second["engine_raw_smiles"])
            self.assertTrue(second["engine_attempts"][0]["from_cache"])

    def test_one_real_image_normalization_retry_preserves_both_raw_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = self.fixture(root)
            converter, calls = self.converter(["C1CC", "CCO"], retry=True)
            result = converter.convert_one(item, preprocess_dir=str(root / "inputs"))
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0], calls[1])
            self.assertEqual(
                [a["raw_smiles"] for a in result["engine_attempts"]], ["C1CC", "CCO"]
            )
            self.assertEqual(result["raw_smiles"], result["engine_raw_smiles"])
            self.assertEqual(result["OCSR_status"], "success")

    def test_exact_native_stereo_loss_cache_remains_review_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = self.fixture(root)
            converter, calls = self.converter(
                ["C[C@H]1CC(C)(O)C1"], cache=str(root / "cache.sqlite")
            )
            first = converter.convert_one(item)
            second = converter.convert_one(item)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["raw_smiles"], second["raw_smiles"])
            self.assertEqual(
                second["OCSR_quality_flag"], "stereochemistry_not_retained"
            )
            self.assertEqual(second["OCSR_status"], "review_required")
            self.assertTrue(second["engine_attempts"][0]["from_cache"])

    def test_model_fingerprint_change_invalidates_exact_image_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            converter, calls = self.converter(
                ["CCO", "CCN"], cache=str(root / "cache.sqlite")
            )
            item = self.fixture(root)
            first = converter.convert_one(item)
            converter.engines["decimer"].fingerprint = "b" * 64
            second = converter.convert_one(item)
            third = converter.convert_one(item)
            self.assertEqual(len(calls), 2)
            self.assertEqual(first["raw_smiles"], "CCO")
            self.assertEqual(second["raw_smiles"], "CCN")
            self.assertEqual(third["model_fingerprint"], "b" * 64)
            self.assertTrue(third["engine_attempts"][0]["from_cache"])

    def test_two_invalid_observations_stop_without_string_repair_or_unbounded_retry(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            converter, calls = self.converter(["C1CC"], retry=True)
            result = converter.convert_one(
                self.fixture(root), preprocess_dir=str(root / "inputs")
            )
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["raw_smiles"], "C1CC")
            self.assertFalse(result["rdkit_valid"])
            self.assertEqual(result["OCSR_quality_flag"], "invalid_smiles")

    def test_numbered_pair_does_not_infer_or_flip_stereochemistry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = self.fixture(root)
            raw = "C[C@H](O)CC"
            converter, _calls = self.converter([raw])
            rows = converter.convert_batch(
                [
                    {**item, "cpd": "Compound 1-1"},
                    {**item, "cpd": "Compound 1-2", "structure_id": "S0002"},
                ]
            )
            self.assertEqual([r["raw_smiles"] for r in rows], [raw, raw])
            self.assertTrue(all("stereo_correction" not in r for r in rows))

    def test_resource_admission_error_aborts_without_fake_graph_failures(self):
        from patent_sar_extractor.resource_admission import ResourceAdmissionError

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            converter, calls = self.converter(["CCO"])
            item = self.fixture(root)
            with (
                patch.object(
                    converter.engines["decimer"],
                    "predict",
                    side_effect=ResourceAdmissionError(
                        "Controlled headroom wait exhausted"
                    ),
                ) as prediction,
                self.assertRaises(ResourceAdmissionError),
            ):
                converter.convert_batch([item] * 20)
            self.assertEqual(prediction.call_count, 1)
            self.assertEqual(calls, [])

    def test_known_page_render_is_not_accepted_as_a_molecular_crop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = self.fixture(root)
            page = root / "page_001.png"
            page.write_bytes(Path(item["image_path"]).read_bytes())
            converter, calls = self.converter(["CCO"])
            result = converter.convert_one({**item, "image_path": str(page)})
            self.assertEqual(result["OCSR_status"], "image_missing")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
