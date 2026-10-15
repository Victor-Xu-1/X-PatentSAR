"""Reused classification must still own the complete original page source."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz

from patent_sar_extractor.application.stage_classify import execute_classify
from patent_sar_extractor.core import page_ocr_cache as caches


class Progress:
    checkpoint_reused = False

    def start(self, step):
        self.checkpoint_reused = False

    def mark_checkpoint_reused(self):
        self.checkpoint_reused = True


class ClassifySourceCheckpointTests(unittest.TestCase):
    def test_missing_page_after_classification_seal_is_not_reused(self):
        with tempfile.TemporaryDirectory(
            prefix="classify-source-control-"
        ) as temporary:
            root = Path(temporary)
            pdf = root / "original.pdf"
            with fitz.open() as document:
                for index in range(3):
                    page = document.new_page()
                    page.insert_text(
                        (40, 80),
                        f"Original Compound synthesis native text and IC50 activity page {index}",
                    )
                document.save(pdf)
            state = SimpleNamespace(
                args=SimpleNamespace(pdf=str(pdf), reuse_ocr_cache=""),
                force=False,
                patent_id="CONTROL",
                step_dirs={"classify": str(root / "classification")},
                progress=Progress(),
                pipeline_log={"runtime": {}, "steps": {}},
            )
            with (
                patch.object(
                    caches,
                    "get_ocr_engine",
                    side_effect=AssertionError("Native source needs no model"),
                ),
                patch.object(
                    caches,
                    "_build_ocr_engine",
                    side_effect=AssertionError("Native source needs no model"),
                ),
            ):
                execute_classify(state)
                self.assertFalse(state.progress.checkpoint_reused)
                execute_classify(state)
                self.assertTrue(state.progress.checkpoint_reused)
                classification = Path(state.classify_json)
                original = classification.read_bytes()
                changed = json.loads(original)
                changed["page_count"] = True
                classification.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    execute_classify(state)
                self.assertFalse(state.progress.checkpoint_reused)
                classification.write_bytes(original)
                source = Path(state.ocr_cache_path)
                payload = json.loads(source.read_text())
                payload["page_texts"].pop("1")
                source.write_text(json.dumps(payload), encoding="utf-8")
                retained = source.read_bytes()
                with self.assertRaises(RuntimeError):
                    execute_classify(state)
                self.assertFalse(state.progress.checkpoint_reused)
                self.assertEqual(source.read_bytes(), retained)
