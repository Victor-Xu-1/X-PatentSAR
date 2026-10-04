from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

spec = importlib.util.spec_from_file_location(
    "build_frontend",
    Path(__file__).resolve().parents[1] / "tools" / "build_frontend.py",
)
assert spec and spec.loader
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class FrontendPackagingTests(unittest.TestCase):
    def test_local_editor_document_and_wasm_are_fingerprinted_and_packaged(
        self,
    ) -> None:
        (self.dist / "ketcher.html").write_text(
            '<html><script src="assets/editor.js"></script></html>'
        )
        wasm = self.dist / "assets" / "indigo.wasm"
        wasm.write_bytes(b"\x00asm\x01\x00\x00\x00")
        (self.dist / "assets" / "editor.js").write_text("/* local editor */")
        packager.bundle(self.root)
        packager.bundle(self.root, check=True)
        self.assertEqual(
            (self.destination / "assets" / "indigo.wasm").read_bytes(),
            wasm.read_bytes(),
        )
        self.assertTrue((self.destination / "ketcher.html").is_file())
        wasm.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "differ"):
            packager.bundle(self.root, check=True)

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

    def test_rebuild_removes_only_verified_setuptools_static_copy(self) -> None:
        packager.bundle(self.root)
        staged = self.root / "build" / "lib" / "patent_sar_extractor" / "web" / "static"
        shutil.copytree(self.destination, staged)
        unrelated = staged.parent / "keep.py"
        unrelated.write_text("# unrelated generated module")
        packager.bundle(self.root, check=True)
        self.assertTrue(staged.exists(), "Check mode must not mutate build state")
        (self.dist / "assets" / "app.js").unlink()
        (self.dist / "assets" / "next.js").write_text("console.info('next');")
        packager.bundle(self.root)
        self.assertFalse(
            staged.exists(), "Setuptools must not retain obsolete hashed JS"
        )
        self.assertTrue(unrelated.exists())

    def test_unmanaged_staged_assets_are_preserved(self) -> None:
        packager.bundle(self.root)
        staged = self.root / "build" / "lib" / "patent_sar_extractor" / "web" / "static"
        staged.mkdir(parents=True)
        asset = staged / "user.js"
        asset.write_text("user change")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            packager.bundle(self.root)
        self.assertEqual(asset.read_text(), "user change")

    def test_linked_build_directory_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as external:
            (self.root / "build").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic"):
                packager.bundle(self.root)
            self.assertEqual(list(Path(external).iterdir()), [])

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


class WorkflowPackagingTests(unittest.TestCase):
    def test_runner_paths_are_initialized_after_job_scheduling(self) -> None:
        workflow = yaml.safe_load(
            (
                Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
            ).read_text()
        )
        for job in workflow["jobs"].values():
            for value in job.get("env", {}).values():
                self.assertNotRegex(
                    str(value),
                    r"\$\{\{\s*runner\.",
                    "GitHub rejects runner context in job-level env before creating a job",
                )
        initialization = workflow["jobs"]["test"]["steps"][0]["run"]
        self.assertIn("$RUNNER_TEMP/x-patentsar-api-tests", initialization)
        self.assertIn("$RUNNER_TEMP/x-patentsar-browser-tests", initialization)
        self.assertIn('"$GITHUB_ENV"', initialization)


if __name__ == "__main__":
    unittest.main()
