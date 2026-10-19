"""Neither model bytes nor an editable installed RECORD alone is source identity."""

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor.core.text_ocr import identity


class AuxiliaryTextIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.spec = {"models": []}
        for name in ("inference.json", "inference.yml", "inference.pdiparams"):
            content = ("Controlled original " + name).encode()
            (self.root / name).write_bytes(content)
            self.spec["models"].append(
                {
                    "file": name,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )

    def test_all_model_files_are_hash_checked(self):
        self.assertEqual(len(identity.model_files(self.root, self.spec)), 3)
        path = self.root / "inference.yml"
        original = path.read_bytes()
        path.write_bytes(b"x" + original[1:])
        with self.assertRaises(ValueError):
            identity.model_files(self.root, self.spec)

    def test_model_symlink_and_relative_root_are_refused(self):
        with self.assertRaises(ValueError):
            identity.model_files(Path("relative"), self.spec)
        path = self.root / "inference.yml"
        saved = self.root / "original.yml"
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaises(ValueError):
            identity.model_files(self.root, self.spec)

    def test_bad_model_is_refused_before_distribution_queries(self):
        (self.root / "inference.json").write_text("bad")
        with (
            patch.object(identity, "recipe", return_value=self.spec),
            patch.object(identity.sys, "version_info", (3, 10, 20)),
            patch.object(identity.metadata, "version") as versions,
            self.assertRaises(ValueError),
        ):
            identity.text_identity(self.root)
        versions.assert_not_called()

    def test_incompatible_native_python_is_refused(self):
        with (
            patch.object(identity.sys, "version_info", (3, 11)),
            self.assertRaises(ValueError),
        ):
            identity.text_identity(self.root)

    def sdk(self):
        folder = self.root / "sdk"
        folder.mkdir()
        reviewed, records = {}, []
        for index in range(10):
            name = f"sdk/part_{index}.py"
            payload = f"value = {index}\n".encode()
            (self.root / name).write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            reviewed[name] = digest
            b64 = base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip("=")
            records.append(f"{name},sha256={b64},{len(payload)}")
        payload = json.dumps({"sdk": reviewed})
        (self.root / "text-ocr-sdk.json").write_text(payload)
        distribution = SimpleNamespace(
            read_text=lambda _name: "\n".join(records),
            locate_file=lambda name: self.root / name,
        )
        spec = {
            "sdk_wheels": [{"name": "sdk", "prefix": "sdk"}],
            "sdk_inventory": {
                "generator": "tools/build_text_ocr_resources.py",
                "sha256": hashlib.sha256(payload.encode()).hexdigest(),
            },
        }
        return spec, distribution, records

    def test_installed_sdk_matches_both_record_and_reviewed_wheel(self):
        spec, distribution, _ = self.sdk()
        with (
            patch.object(identity, "RESOURCES", self.root),
            patch.object(identity.metadata, "distribution", return_value=distribution),
        ):
            self.assertEqual(len(identity._sdk_inventory(spec)), 10)

    def test_changed_generated_manifest_is_refused_before_native_package_queries(self):
        spec, distribution, _ = self.sdk()
        with (self.root / "text-ocr-sdk.json").open("a") as stream:
            stream.write("\n")
        with (
            patch.object(identity, "RESOURCES", self.root),
            patch.object(
                identity.metadata, "distribution", return_value=distribution
            ) as native,
            self.assertRaisesRegex(ValueError, "fingerprint"),
        ):
            identity._sdk_inventory(spec)
        native.assert_not_called()

    def test_generated_inventory_path_or_digest_cannot_escape_reviewed_packages(self):
        for path, digest in (
            ("sdk/../private.py", "a" * 64),
            ("sdk/bad.py", "not-a-sha"),
        ):
            spec, _, _ = self.sdk()
            target = self.root / "text-ocr-sdk.json"
            packet = json.loads(target.read_text())
            packet["sdk"].pop(next(iter(packet["sdk"])))
            packet["sdk"][path] = digest
            content = json.dumps(packet)
            target.write_text(content)
            spec["sdk_inventory"]["sha256"] = hashlib.sha256(
                content.encode()
            ).hexdigest()
            with self.assertRaisesRegex(ValueError, "unsafe"):
                identity.sdk_manifest(self.root, spec)
            # Each controlled package is recreated for the next independent case.
            for item in (self.root / "sdk").iterdir():
                item.unlink()
            (self.root / "sdk").rmdir()

    def test_editing_sdk_and_its_record_cannot_change_reviewed_hashes(self):
        spec, distribution, records = self.sdk()
        payload = b"changed source\n"
        (self.root / "sdk/part_0.py").write_bytes(payload)
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .decode()
            .rstrip("=")
        )
        records[0] = f"sdk/part_0.py,sha256={digest},{len(payload)}"
        with (
            patch.object(identity, "RESOURCES", self.root),
            patch.object(identity.metadata, "distribution", return_value=distribution),
            self.assertRaises(ValueError),
        ):
            identity._sdk_inventory(spec)

    def test_missing_sdk_inventory_is_not_an_empty_qualified_install(self):
        spec, distribution, records = self.sdk()
        records.pop()
        with (
            patch.object(identity, "RESOURCES", self.root),
            patch.object(identity.metadata, "distribution", return_value=distribution),
            self.assertRaises(ValueError),
        ):
            identity._sdk_inventory(spec)
