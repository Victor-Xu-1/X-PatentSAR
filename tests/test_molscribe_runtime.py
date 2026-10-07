"""Pinned local adapter contracts, without cold model downloads or broad tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor.core.ocsr.engines.molscribe_engine import MolScribeEngine
from patent_sar_extractor.core.ocsr.molscribe_identity import rescue_recipe
from patent_sar_extractor.web.environment_specs import complete_components, recipe_path
from patent_sar_extractor.workers.environment_assets import OfficialRedirect, _verify


class MolScribeRuntimeTests(unittest.TestCase):
    def test_fixed_recipe_includes_hashes_and_complete_setup_owns_both_parts(self):
        recipe = rescue_recipe()
        self.assertEqual(
            recipe["sdk"]["commit"], "7296a30413eb55436702011efdff78131f66d162"
        )
        self.assertEqual(len(recipe["sdk"]["sha256"]), 64)
        self.assertEqual(recipe["model"]["size"], 1134173494)
        self.assertEqual(recipe["distributions"]["torch"], "2.13.0+cpu")
        self.assertIn("molscribe", complete_components())
        self.assertIn("molscribe-models", complete_components())
        self.assertEqual(len(complete_components()), 8)
        lock = recipe_path("molscribe-requirements.txt").read_text()
        self.assertIn("torch==2.13.0+cpu", lock)
        self.assertIn("--hash=sha256:", lock)

    def test_rescue_cpu_safe_loading_policy_cannot_inherit_gpu_or_parent_pythonpath(
        self,
    ):
        with patch.dict(
            os.environ,
            {
                "PYTHONPATH": "/bad/site-packages",
                "CUDA_VISIBLE_DEVICES": "0",
                "TORCH_FORCE_WEIGHTS_ONLY_LOAD": "0",
            },
        ):
            env = MolScribeEngine()._build_env()
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "-1")
        self.assertEqual(env["TORCH_FORCE_WEIGHTS_ONLY_LOAD"], "1")
        self.assertEqual(env["OMP_NUM_THREADS"], "2")

    def test_declared_asset_size_bounds_hashing_instead_of_unrelated_default_limit(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "asset"
            path.write_bytes(b"ab")
            with patch(
                "patent_sar_extractor.workers.environment_assets.file_sha256",
                return_value="a" * 64,
            ) as digest:
                _verify(path, 2, "a" * 64, None)
            digest.assert_called_once_with(path, limit=2)

    def test_native_probe_receipt_matches_the_single_inspection_contract(self):
        from patent_sar_extractor.workers.molscribe_probe import probe_local_rescue

        recipe = rescue_recipe()
        native = SimpleNamespace(
            version=SimpleNamespace(cuda=None),
            cuda=SimpleNamespace(is_available=lambda: False),
        )
        sdk = SimpleNamespace(
            MolScribe=SimpleNamespace(predict_image_file=lambda: None)
        )
        with (
            patch.dict(sys.modules, {"torch": native, "molscribe": sdk}),
            patch(
                "patent_sar_extractor.workers.molscribe_probe.importlib.metadata.version",
                side_effect=lambda name: recipe["distributions"][name],
            ),
            patch(
                "patent_sar_extractor.workers.molscribe_probe.sys.version_info",
                (3, 10, 20),
            ),
        ):
            receipt = probe_local_rescue({"role": "molscribe"}, {"checks": []})
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["version"], "1.1.1")
        self.assertTrue(all(check["ok"] for check in receipt["checks"]))

    def test_missing_native_confidence_is_not_fabricated_as_zero(self):
        from PIL import Image

        from patent_sar_extractor.core.ocsr.molscribe_model import PinnedMolScribeModel

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.png"
            Image.new("RGB", (20, 20), "white").save(path)
            model = PinnedMolScribeModel.__new__(PinnedMolScribeModel)
            model.identity = {
                "fingerprint": "a" * 64,
                "adapter_version": "constrained-stereo-v1",
            }
            model.model = SimpleNamespace(
                predict_image_file=lambda *args, **kwargs: {"smiles": "CCO"}
            )
            output = model.predict(str(path))
            self.assertIsNone(output["model_confidence"])

    def test_unrelated_or_non_https_redirects_cannot_be_used_for_fixed_assets(self):
        for url in (
            "http://huggingface.co/model",
            "https://evil.example/file",
            "https://user:password@huggingface.co/file",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                OfficialRedirect().redirect_request(
                    None, None, 302, "redirect", {}, url
                )
