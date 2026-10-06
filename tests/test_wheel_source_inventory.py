"""Fresh staging and exact package inventory, with no runtime/model writes."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from build_wheel import stage
from wheel_sources import (
    PACKAGE,
    STATIC,
    package_files,
    source_file,
    verify_package_files,
)


class WheelSourceInventoryTests(unittest.TestCase):
    def test_hidden_frontend_manifest_is_explicit_package_data(self):
        project = tomllib.loads((TOOLS.parent / "pyproject.toml").read_text())
        files = project["tool"]["setuptools"]["package-data"][
            "patent_sar_extractor.web"
        ]
        self.assertIn("static/.bundle.json", files)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-wheel-inventory-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repository"
        self.root.mkdir()
        self.tracked = ["src/" + PACKAGE + "contracts.py"]
        self._write(self.tracked[0], b"__version__ = '0.1.0'\n")
        for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE", "NOTICE"):
            self._write(name, name.encode())
        self._write("src/" + STATIC + "index.html", b"<html></html>")
        import hashlib

        self._write(
            "src/" + STATIC + ".bundle.json",
            json.dumps(
                {
                    "generator": "tools/build_frontend.py",
                    "files": {
                        "index.html": hashlib.sha256(b"<html></html>").hexdigest()
                    },
                }
            ).encode(),
        )

    def _write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def _inventory(self):
        return package_files(self.root, tracked=self.tracked)

    @staticmethod
    def _archive(expected, *, extra=False, missing=False, changed=False):
        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as archive:
            for index, (name, path) in enumerate(expected.items()):
                if missing and index == 0:
                    continue
                archive.writestr(
                    name,
                    b"obsolete bytes" if changed and index == 0 else path.read_bytes(),
                )
            if extra:
                archive.writestr(
                    PACKAGE + "core/binding_completion.py", b"obsolete module"
                )
            archive.writestr(
                "x_patentsar-0.1.0.dist-info/RECORD",
                b"metadata excluded from source inventory",
            )
        return ZipFile(buffer)

    def test_current_package_bytes_match(self):
        expected = self._inventory()
        with self._archive(expected) as archive:
            self.assertEqual(verify_package_files(archive, expected), 3)

    def test_deleted_source_returning_from_old_build_is_rejected(self):
        expected = self._inventory()
        with (
            self._archive(expected, extra=True) as archive,
            self.assertRaisesRegex(ValueError, "extra=.*binding_completion"),
        ):
            verify_package_files(archive, expected)

    def test_missing_current_source_is_rejected(self):
        expected = self._inventory()
        with (
            self._archive(expected, missing=True) as archive,
            self.assertRaisesRegex(ValueError, "missing=.*contracts"),
        ):
            verify_package_files(archive, expected)

    def test_stale_bytes_with_current_filename_are_rejected(self):
        expected = self._inventory()
        with (
            self._archive(expected, changed=True) as archive,
            self.assertRaisesRegex(ValueError, "source bytes"),
        ):
            verify_package_files(archive, expected)

    def test_untracked_source_and_old_build_are_preserved_not_staged(self):
        stale = self._write(
            "build/lib/" + PACKAGE + "core/binding_completion.py", b"old staging"
        )
        private = self._write("src/" + PACKAGE + "private.py", b"untracked user work")
        work = self.root.parent / "fresh-builds"
        with patch("build_wheel.package_files", return_value=self._inventory()):
            first = stage(self.root, work)
            second = stage(self.root, work)
        self.assertNotEqual(first, second)
        self.assertEqual(stale.read_bytes(), b"old staging")
        self.assertEqual(private.read_bytes(), b"untracked user work")
        self.assertFalse((first / "build").exists())
        self.assertFalse((first / "src" / PACKAGE / "private.py").exists())
        self.assertEqual(
            (first / self.tracked[0]).read_bytes(),
            (self.root / self.tracked[0]).read_bytes(),
        )

    def test_linked_source_is_rejected(self):
        target = self.root / self.tracked[0]
        target.unlink()
        outside = self.root.parent / "private.py"
        outside.write_bytes(b"outside")
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escapes|symbolic"):
            self._inventory()

    def test_linked_parent_inside_root_is_rejected(self):
        actual = self.root / "real"
        actual.mkdir()
        (actual / "item.py").write_bytes(b"inside")
        (self.root / "linked").symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic"):
            source_file(self.root, "linked/item.py")

    def test_unsafe_paths_are_rejected(self):
        for name in ("../private.py", "/private.py", "src\\private.py"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsafe"):
                source_file(self.root, name)

    def test_missing_tracked_file_is_rejected(self):
        (self.root / self.tracked[0]).unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self._inventory()

    def test_unexpected_tracked_package_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            package_files(self.root, tracked=["secrets.py"])

    def test_runtime_input_is_never_a_build_input(self):
        private = self._write("src/" + PACKAGE + "input.pdf", b"private input")
        with self.assertRaisesRegex(ValueError, "file type"):
            package_files(
                self.root, tracked=[*self.tracked, str(private.relative_to(self.root))]
            )
        self.assertEqual(private.read_bytes(), b"private input")

    def test_changed_frontend_manifest_bytes_are_rejected(self):
        self._write("src/" + STATIC + "index.html", b"changed UI")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self._inventory()

    def test_unsafe_frontend_inventory_is_rejected(self):
        self._write(
            "src/" + STATIC + ".bundle.json",
            json.dumps(
                {
                    "generator": "tools/build_frontend.py",
                    "files": {"../private.js": "0" * 64},
                }
            ).encode(),
        )
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self._inventory()

    def test_incomplete_product_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            package_files(self.root, tracked=[])
