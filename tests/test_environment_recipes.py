"""Catalog, immutable assets and private-plan regression tests (no SDK mocks)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
import uuid
import zipfile
from pathlib import Path

from patent_sar_extractor.web.environment_models import EnvironmentComponent
from patent_sar_extractor.web.environment_specs import (
    component_catalog,
    resolved_components,
)
from patent_sar_extractor.workers.environment_assets import (
    download,
    extract_model_group,
)
from patent_sar_extractor.workers.environment_files import (
    atomic_json,
    checked_directory,
)
from patent_sar_extractor.workers.environment_plan import (
    COMPONENT_IDS,
    read_plan,
    wait_for_owner,
)


class RecipeFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            dir=os.environ.get("PATENTSAR_WEB_TEST_ROOT")
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identifier = uuid.uuid4().hex
        self.operation = self.root / self.identifier
        self.operation.mkdir(mode=0o700)
        self.cache = self.root / "cache"
        self.cache.mkdir(mode=0o700)
        self.install = self.root / "managed"
        self.install.mkdir(mode=0o700)
        self.marker = self.install / ".x-patentsar-environments.json"
        self.marker.write_text(
            json.dumps(
                {"schema_version": 1, "product": "X-PatentSAR", "uid": os.getuid()}
            )
        )
        self.payload = {
            "schema_version": 1,
            "operation_id": self.identifier,
            "action": "inspect",
            "component_ids": ["admet"],
            "install_root": str(self.install),
            "cache_root": str(self.cache),
            "bindings": dict.fromkeys(COMPONENT_IDS),
        }
        self.plan_file = self.operation / "environment-plan.json"

    def plan(self, **changes):
        self.plan_file.write_text(json.dumps({**self.payload, **changes}))
        return read_plan(self.plan_file)

    def owner(self, **changes):
        fields = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()
        value = {
            "operation_id": self.identifier,
            "pid": os.getpid(),
            "start_ticks": int(fields[19]),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            **changes,
        }
        (self.operation / "environment-owner.json").write_text(json.dumps(value))


class CatalogTests(RecipeFixture):
    def test_exact_dto_metadata_is_unchecked_without_side_effects(self):
        catalog = component_catalog()
        self.assertEqual({c["id"] for c in catalog}, COMPONENT_IDS)
        for item in catalog:
            card = EnvironmentComponent.model_validate(item)
            self.assertEqual(card.status, "unchecked")
            self.assertIsNone(card.location)
            self.assertIsNone(card.detected_version)
            self.assertFalse(card.checks)
        self.assertEqual(
            resolved_components(["admet-models", "decimer-models"]),
            ["installer", "admet", "admet-models", "decimer", "decimer-models"],
        )
        with self.assertRaises(ValueError):
            resolved_components(["arbitrary-package"])

    def test_plan_rejects_arbitrary_fields_paths_schema_and_duplicate_ids(self):
        for changes in (
            {"url": "https://example.org/"},
            {"schema_version": True},
            {"component_ids": ["admet", "admet"]},
            {"component_ids": ["torch"]},
            {"install_root": str(self.root / "../escape")},
            {"cache_root": "/mnt/e/cache"},
            {"requires_owner_ack": "true"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises((ValueError, TypeError)),
            ):
                self.plan(**changes)
        self.assertEqual(self.plan().operation_id, self.identifier)

    def test_managed_install_requires_marker_and_excludes_replay(self):
        self.marker.write_text("{}")
        with self.assertRaises(ValueError):
            self.plan(action="install")
        self.plan()
        (self.operation / "environment-result.json").write_text("{}")
        with self.assertRaises(ValueError):
            read_plan(self.plan_file)

    def test_owner_ack_exact_identity_missing_timeout_and_cancel(self):
        plan = self.plan(requires_owner_ack=True)
        with self.assertRaises(TimeoutError):
            wait_for_owner(plan, threading.Event(), timeout=0.05)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            wait_for_owner(plan, cancelled)
        self.owner()
        wait_for_owner(plan, threading.Event())
        for changes in (
            {"pid": os.getpid() + 1},
            {"start_ticks": 0},
            {"boot_id": "wrong"},
            {"operation_id": "wrong"},
        ):
            self.owner(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                wait_for_owner(plan, threading.Event())

    def test_private_artifacts_and_symlinks_never_overwrite_unknown_content(self):
        outside = self.root / "user.txt"
        outside.write_text("keep")
        (self.operation / "environment-result.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            atomic_json(self.operation, "environment-result.json", {}, limit=512 * 1024)
        self.assertEqual(outside.read_text(), "keep")
        self.operation.chmod(0o755)
        with self.assertRaises(ValueError):
            checked_directory(self.operation, private=True)


class ModelAssetTests(RecipeFixture):
    def test_cached_tamper_refuses_without_network_or_overwrite(self):
        digest = hashlib.sha256(b"reviewed").hexdigest()
        cached = self.cache / (digest + ".asset")
        cached.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            download(
                "https://files.pythonhosted.org/reviewed.whl",
                self.cache,
                size=8,
                sha256=digest,
                cancel=threading.Event(),
            )
        self.assertEqual(cached.read_bytes(), b"tampered")
        with self.assertRaises(ValueError):
            download(
                "https://unapproved.example/model",
                self.cache,
                size=8,
                sha256=digest,
                cancel=threading.Event(),
            )

    def test_zip_only_extracts_reviewed_members_and_requires_sha_before_load(self):
        archive = self.root / "weights.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("model/saved_model.pb", b"tiny controlled fixture")
            output.writestr("../../not-extracted", b"unsafe")
        group = {
            "directory": "model",
            "url": "https://zenodo.org/reviewed",
            "files": [
                {
                    "path": "model/saved_model.pb",
                    "size": 23,
                    "sha256": hashlib.sha256(b"tiny controlled fixture").hexdigest(),
                }
            ],
        }
        destination = self.root / "verified"
        destination.mkdir()
        extract_model_group(archive, destination, group, threading.Event())
        self.assertEqual(
            (destination / "DECIMER-V2/model/saved_model.pb").read_bytes(),
            b"tiny controlled fixture",
        )
        self.assertFalse((self.root / "not-extracted").exists())
        with self.assertRaises(FileExistsError):
            extract_model_group(archive, destination, group, threading.Event())
        group["files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            extract_model_group(
                archive, self.root / "tampered", group, threading.Event()
            )
        self.assertFalse((self.root / "tampered/DECIMER-V2/model/.model_url").exists())
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            extract_model_group(archive, self.root / "cancelled", group, cancel)
