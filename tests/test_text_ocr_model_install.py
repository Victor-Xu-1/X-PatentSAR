"""Bounded immutable-prefix model copying; no network or private document data."""

import hashlib
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core.text_ocr.identity import model_files, recipe
from patent_sar_extractor.workers.text_ocr_setup import install_text_models


class TextModelInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prefix, self.cache = self.root / "new-owned-prefix", self.root / "cache"
        self.prefix.mkdir()
        self.cache.mkdir()
        self.configuration = self.root / "operator.yaml"
        self.configuration.write_text("preserve-original-configuration")
        self.spec = {"model_revision": recipe()["model_revision"], "models": []}
        for index, name in enumerate(
            ("inference.json", "inference.pdiparams", "inference.yml")
        ):
            data = f"synthetic-model-file-{index}".encode()
            (self.cache / name).write_bytes(data)
            self.spec["models"].append(
                {
                    "file": name,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        self.cancel = threading.Event()

    def install(self, downloader=None, cancel=None):
        expected = (
            "https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec/resolve/"
            + self.spec["model_revision"]
            + "/"
        )

        def existing(url, cache, **details):
            item = next(m for m in self.spec["models"] if expected + m["file"] == url)
            self.assertEqual(details["size"], item["size"])
            self.assertEqual(details["sha256"], item["sha256"])
            return self.cache / item["file"]

        with (
            patch(
                "patent_sar_extractor.workers.text_ocr_setup.recipe",
                return_value=self.spec,
            ),
            patch(
                "patent_sar_extractor.workers.text_ocr_setup.download",
                side_effect=downloader or existing,
            ) as source,
        ):
            result = install_text_models(
                self.prefix, self.cache, cancel or self.cancel, None
            )
        self.assertEqual(source.call_count, 3)
        self.assertEqual(
            self.configuration.read_text(), "preserve-original-configuration"
        )
        return result

    def test_fixed_files_copy_and_verify_without_touching_operator_configuration(self):
        result = self.install()
        self.assertEqual(result, self.prefix / "models")
        self.assertEqual(
            model_files(result, self.spec),
            [(m["file"], m["sha256"]) for m in self.spec["models"]],
        )

    def test_precancelled_install_never_downloads_or_copies_files(self):
        self.cancel.set()
        with (
            patch("patent_sar_extractor.workers.text_ocr_setup.download") as source,
            self.assertRaises(InterruptedError),
        ):
            install_text_models(self.prefix, self.cache, self.cancel, None)
        source.assert_not_called()
        self.assertEqual(list((self.prefix / "models").iterdir()), [])

    def test_midcopy_cancellation_keeps_bounded_partial_evidence_without_activation(
        self,
    ):
        data = b"a" * (3 * 1024 * 1024)
        self.spec["models"][0].update(
            size=len(data), sha256=hashlib.sha256(data).hexdigest()
        )
        (self.cache / "inference.json").write_bytes(data)
        target = self.prefix / "models/inference.json"

        class CancelAfterOwnedChunk:
            def is_set(self):
                return target.exists() and target.stat().st_size >= 1024 * 1024

        with self.assertRaises(InterruptedError):
            self.install(cancel=CancelAfterOwnedChunk())
        self.assertEqual(target.stat().st_size, 1024 * 1024)
        self.assertFalse((target.parent / "inference.pdiparams").exists())
        self.assertEqual(
            self.configuration.read_text(), "preserve-original-configuration"
        )

    def test_modified_cached_content_is_not_promoted(self):
        path = self.cache / "inference.json"
        path.write_bytes(b"x" * self.spec["models"][0]["size"])
        with self.assertRaisesRegex(ValueError, "content changed"):
            self.install()
        self.assertEqual(
            self.configuration.read_text(), "preserve-original-configuration"
        )

    def test_oversized_asset_is_refused_before_creating_a_target_file(self):
        (self.cache / "inference.json").write_bytes(
            b"x" * (self.spec["models"][0]["size"] + 1)
        )
        with self.assertRaisesRegex(ValueError, "size/type"):
            self.install()
        self.assertFalse((self.prefix / "models/inference.json").exists())

    def test_cached_symlink_is_not_followed_or_deleted(self):
        path = self.cache / "inference.json"
        path.unlink()
        path.symlink_to(self.configuration)
        with self.assertRaises((OSError, ValueError)):
            self.install()
        self.assertTrue(path.is_symlink())
        self.assertEqual(
            self.configuration.read_text(), "preserve-original-configuration"
        )

    def test_existing_unknown_model_directory_is_never_replaced(self):
        models = self.prefix / "models"
        models.mkdir()
        preserved = models / "inference.json"
        preserved.write_bytes(b"user-owned-content")
        with self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual(preserved.read_bytes(), b"user-owned-content")


@unittest.skipUnless(
    os.environ.get("PATENTSAR_TEST_TEXT_OCR_MODELS"),
    "Explicit reviewed public model files required",
)
class ReviewedTextModelCopyTests(unittest.TestCase):
    def test_actual_reviewed_files_copy_and_rehash_without_a_download(self):
        source = Path(os.environ["PATENTSAR_TEST_TEXT_OCR_MODELS"])
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)

            def cached(url, cache, **details):
                name = url.rsplit("/", 1)[-1]
                self.assertIn(name, {m["file"] for m in recipe()["models"]})
                return source / name

            with patch(
                "patent_sar_extractor.workers.text_ocr_setup.download",
                side_effect=cached,
            ) as downloads:
                result = install_text_models(prefix, prefix, threading.Event(), None)
            self.assertEqual(downloads.call_count, 3)
            self.assertEqual(len(model_files(result, recipe())), 3)
