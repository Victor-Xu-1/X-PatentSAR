"""Portable provisioning refuses unknown destinations and unverified wheels."""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

from test_web_support import WebFixture

TOOL = Path(__file__).resolve().parents[1] / "tools/prepare_admet_models.py"
spec = importlib.util.spec_from_file_location("prepare_admet_models", TOOL)
assert spec is not None and spec.loader is not None
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


class ProvisionTests(WebFixture, unittest.TestCase):
    def test_wrong_wheel_never_creates_or_overwrites_destination(self):
        wheel = self.root / "invalid.whl"
        wheel.write_bytes(b"not the official distribution")
        destination = self.root / "models"
        with self.assertRaises(ValueError):
            provision.prepare(wheel, destination)
        self.assertFalse(destination.exists())
        destination.mkdir()
        marker = destination / "user-owned.txt"
        marker.write_text("Preserve this exact user data")
        with self.assertRaises(ValueError):
            provision.prepare(wheel, destination)
        self.assertEqual(marker.read_text(), "Preserve this exact user data")

    def test_existing_unknown_or_linked_content_is_not_accepted(self):
        destination = self.root / "unknown"
        destination.mkdir()
        with self.assertRaises(ValueError):
            provision.existing_bundle(destination)
        marker = destination / "manifest.json"
        marker.symlink_to(self.pdf)
        with self.assertRaises(ValueError):
            provision.existing_bundle(destination)
        self.assertTrue(marker.is_symlink())

    @unittest.skipUnless(
        os.environ.get("PATENTSAR_ADMET_WHEEL"),
        "Official model wheel is an explicit external integration input",
    )
    def test_real_official_wheel_model_hash_no_drugbank_and_idempotence(self):
        wheel = Path(os.environ["PATENTSAR_ADMET_WHEEL"])
        destination = self.root / "verified-models"
        manifest = provision.prepare(wheel, destination)
        self.assertEqual(manifest["model_sha256"], provision.ADMET_BUNDLE_SHA256)
        self.assertEqual(len(manifest["files"]), 11)
        self.assertFalse(manifest["drugbank_reference"])
        self.assertFalse(
            any("drugbank" in p.name.lower() for p in destination.rglob("*"))
        )
        before = {
            p: (p.stat().st_size, p.stat().st_mtime_ns)
            for p in destination.rglob("*")
            if p.is_file()
        }
        self.assertEqual(provision.prepare(wheel, destination), manifest)
        self.assertEqual(
            before, {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in before}
        )
        (destination / "unknown.txt").write_text("do not replace")
        with self.assertRaises(ValueError):
            provision.prepare(wheel, destination)
        self.assertTrue((destination / "unknown.txt").is_file())
