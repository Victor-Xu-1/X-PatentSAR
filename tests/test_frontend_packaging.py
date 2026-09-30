from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "build_frontend",
    Path(__file__).resolve().parents[1] / "tools" / "build_frontend.py",
)
assert spec and spec.loader
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class FrontendPackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dist = self.root / "frontend" / "dist"
        self.dist.mkdir(parents=True)
        (self.dist / "index.html").write_text(
            '<html><script src="assets/app.js"></script></html>'
        )
        (self.dist / "assets").mkdir()
        (self.dist / "assets" / "app.js").write_text('document.title = "X-PatentSAR";')
        self.destination = self.root / "src" / "patent_sar_extractor" / "web" / "static"

    def test_real_bundle_copy_check_and_rebuild(self) -> None:
        packager.bundle(self.root)
        packager.bundle(self.root, check=True)
        self.assertEqual(
            (self.destination / "assets" / "app.js").read_bytes(),
            (self.dist / "assets" / "app.js").read_bytes(),
        )
        (self.dist / "assets" / "app.js").unlink()
        (self.dist / "assets" / "updated.js").write_text("console.info('updated');")
        with self.assertRaisesRegex(ValueError, "differ"):
            packager.bundle(self.root, check=True)
        packager.bundle(self.root)
        self.assertFalse((self.destination / "assets" / "app.js").exists())
        self.assertTrue((self.destination / "assets" / "updated.js").exists())

    def test_modified_or_unmanaged_destination_is_preserved(self) -> None:
        packager.bundle(self.root)
        changed = self.destination / "assets" / "app.js"
        changed.write_text("user modification")
        with self.assertRaisesRegex(ValueError, "modified"):
            packager.bundle(self.root)
        self.assertEqual(changed.read_text(), "user modification")
        (self.destination / packager.MARKER).unlink()
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            packager.bundle(self.root)

    def test_untrusted_build_symlink_is_rejected(self) -> None:
        outside = self.root / "private.txt"
        outside.write_text("private")
        (self.dist / "assets" / "private.js").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symbolic"):
            packager.bundle(self.root)
        self.assertFalse(self.destination.exists())

    def test_missing_or_unexpected_output_is_rejected(self) -> None:
        (self.dist / "index.html").unlink()
        with self.assertRaisesRegex(ValueError, "Build the frontend"):
            packager.bundle(self.root)
        (self.dist / "index.html").write_text("<html></html>")
        (self.dist / ".env").write_text("secret")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            packager.bundle(self.root)

    def test_linked_destination_parent_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as external:
            (self.root / "src").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "inside the repository"):
                packager.bundle(self.root)
            self.assertEqual(list(Path(external).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
