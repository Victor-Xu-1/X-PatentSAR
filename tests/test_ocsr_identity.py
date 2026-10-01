"""Installed support modules are verified before any scientific code is loaded."""

from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.ocsr.model_identity import _verified_sdk_sources


class SDKIdentityTests(unittest.TestCase):
    def test_real_support_files_must_match_install_record_and_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sdk = root / "DECIMER"
            sdk.mkdir()
            record = []
            for name in ("pre_process.py", "utils.py"):
                data = b"raise RuntimeError('verification must not execute me')\n"
                (sdk / name).write_bytes(data)
                digest = (
                    base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                    .decode()
                    .rstrip("=")
                )
                record.append(f"DECIMER/{name},sha256={digest},{len(data)}")

            class Distribution:
                def locate_file(self, name):
                    return root / name

                def read_text(self, name):
                    return "\n".join(record) if name == "RECORD" else None

            distribution = Distribution()
            verified_root, inventory = _verified_sdk_sources(distribution)
            self.assertEqual(verified_root, sdk)
            self.assertEqual(
                [name for name, _ in inventory], ["pre_process.py", "utils.py"]
            )
            source = sdk / "utils.py"
            original = source.read_bytes()
            source.write_bytes(original + b"# changed\n")
            with self.assertRaisesRegex(ValueError, "differs"):
                _verified_sdk_sources(distribution)
            source.unlink()
            outside = root / "external.py"
            outside.write_bytes(original)
            source.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "unsafe"):
                _verified_sdk_sources(distribution)
