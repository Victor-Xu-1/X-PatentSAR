"""Core input bytes and masked/display distinctions, with bounded stat-cache reuse."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from patent_sar_extractor.web.core_recognition_source import (
    _inputs,
    core_source_current,
)


class CoreRecognitionSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "smiles").mkdir()
        self.source = self.root / "masked-input.png"
        self.source.write_bytes(b"controlled raw original-input bytes")
        self.display = self.root / "display.png"
        self.display.write_bytes(b"different visible crop with printed label")
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.file = self.root / "smiles/smiles_results.json"
        self.file.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "cpd_id": "Compound 1",
                            "structure_id": "S1",
                            "image_hash": self.digest,
                            "ocsr_original_input": str(self.source),
                        }
                    ]
                }
            )
        )
        self.compound = SimpleNamespace(
            id="Compound 1",
            structure_id="S1",
            smiles="CCO",
            recognition=SimpleNamespace(
                stereochemistry=SimpleNamespace(image_sha256=self.digest)
            ),
        )
        self.project, self.row = (
            {"run_root": str(self.root)},
            {"image_path": str(self.display)},
        )
        self.addCleanup(_inputs.cache_clear)

    def test_exact_original_input_not_display_crop_decides_currentness(self):
        self.assertTrue(core_source_current(self.project, self.row, self.compound))
        self.source.write_bytes(self.source.read_bytes() + b"changed")
        self.assertFalse(core_source_current(self.project, self.row, self.compound))

    def test_changed_index_identity_and_missing_source_cannot_reuse_old_hashes(self):
        self.assertTrue(core_source_current(self.project, self.row, self.compound))
        self.file.write_text(json.dumps({"records": []}))
        self.assertFalse(core_source_current(self.project, self.row, self.compound))
        self.source.unlink()
        self.assertFalse(core_source_current(self.project, self.row, self.compound))

    def test_unknown_foreign_input_path_is_rejected_without_reading_outside_root(self):
        record = json.loads(self.file.read_text())
        record["records"][0]["ocsr_original_input"] = "/outside/foreign.png"
        self.file.write_text(json.dumps(record))
        self.assertFalse(core_source_current(self.project, self.row, self.compound))
