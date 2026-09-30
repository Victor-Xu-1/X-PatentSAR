"""Canonical lock-derived recipes cannot overwrite unknown or modified content."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "build_environment_resources",
    Path(__file__).resolve().parents[1] / "tools/build_environment_resources.py",
)
assert spec and spec.loader
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

EXPORT = "pymupdf==1.0 --hash=sha256:example\nrdkit==1.0 --hash=sha256:example\nrapidocr-onnxruntime==1.0 --hash=sha256:example\n"


class EnvironmentResourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "uv.lock").write_text("controller fixture lock")
        self.destination = self.root / "src/patent_sar_extractor/defaults/environments"
        self.command = patch.object(
            generator.subprocess,
            "run",
            side_effect=lambda args, **_: subprocess.CompletedProcess(
                args,
                0,
                "uv 0.11.31 fixture\n" if args[1] == "--version" else EXPORT,
                "",
            ),
        )
        self.command.start()
        self.addCleanup(self.command.stop)

    def test_generated_resources_are_reproducible_and_detect_lock_drift(self):
        generator.build(self.root, "controlled-uv")
        before = {p.name: p.read_bytes() for p in self.destination.iterdir()}
        generator.build(self.root, "controlled-uv", check=True)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.destination.iterdir()}
        )
        (self.root / "uv.lock").write_text("changed canonical lock")
        with self.assertRaisesRegex(ValueError, "differ"):
            generator.build(self.root, "controlled-uv", check=True)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.destination.iterdir()}
        )

    def test_unknown_and_modified_requirements_are_never_overwritten(self):
        self.destination.mkdir(parents=True)
        path = self.destination / "base-requirements.txt"
        path.write_text("operator content")
        with self.assertRaisesRegex(ValueError, "Unmanaged"):
            generator.build(self.root, "controlled-uv")
        self.assertEqual(path.read_text(), "operator content")
        path.unlink()
        generator.build(self.root, "controlled-uv")
        path.write_text("operator content")
        with self.assertRaisesRegex(ValueError, "modified"):
            generator.build(self.root, "controlled-uv")
        self.assertEqual(path.read_text(), "operator content")

    def test_symlinked_provenance_is_rejected_without_external_writes(self):
        generator.build(self.root, "controlled-uv")
        path = self.destination / "base-runtime.json"
        external = self.root / "operator.json"
        external.write_bytes(path.read_bytes())
        before = external.read_bytes()
        path.unlink()
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symbolic"):
            generator.build(self.root, "controlled-uv")
        self.assertEqual(external.read_bytes(), before)

    def test_render_requires_actual_consumers_and_refuses_other_authorities(self):
        for value in ("rdkit==1.0\n", EXPORT + "--index-url https://unknown.invalid\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                generator.rendered(self.root, value)
        requirements, metadata = generator.rendered(self.root, EXPORT)
        self.assertIn(generator.GENERATOR, requirements)
        self.assertEqual(json.loads(metadata)["python"], "3.12")


if __name__ == "__main__":
    unittest.main()
