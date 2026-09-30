"""Real auth, SQLite and owned processes with the package boundary controlled."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.environment_paths import ManagedStorage
from patent_sar_extractor.web.processes import SubprocessRunner

CARD = {
    "id": "base",
    "name": "Controlled package boundary",
    "description": "API fixture, not installed-product evidence",
    "version": "3.12",
    "detected_version": None,
    "status": "unchecked",
    "location": None,
    "kind": "runtime",
    "group": "base",
    "required": True,
    "installable": True,
    "download_bytes": None,
    "installed_bytes": None,
    "license": "fixture",
    "source_url": "https://example.invalid/fixture",
    "checks": [],
    "problem": None,
}

WORKER = r"""
import json, sys, time
from pathlib import Path
root = Path(sys.argv[1])
mode = sys.argv[2]
plan = json.loads((root / 'environment-plan.json').read_text())
while not (root / 'environment-owner.json').exists():
    time.sleep(.01)
if mode == 'wait':
    time.sleep(30)
if mode == 'fail':
    print('Controlled dependency verification failure', flush=True)
    sys.exit(1)
card = json.loads(sys.argv[3])
install = plan['action'] == 'install'
card.update(status='ready' if install else 'missing', detected_version='3.12' if install else None,
            location=plan['bindings']['base'] if install else None,
            checks=[{'name':'controlled-boundary','ok':install,'message':'not a real-package claim'}],
            problem=None if install else 'Controlled missing package')
result = {'schema_version':1, 'operation_id':plan['operation_id'], 'components':[card],
          'bindings':{'base':plan['bindings']['base']} if install else {}}
temporary = root / 'result.pending'
temporary.write_text(json.dumps(result))
temporary.replace(root / 'environment-result.json')
"""


class BoundaryRunner(SubprocessRunner):
    def __init__(self, mode="complete"):
        super().__init__()
        self.mode = mode

    def command(self, spec):
        return [
            sys.executable,
            "-c",
            WORKER,
            spec.output_dir,
            self.mode,
            json.dumps(CARD),
        ]


class EnvironmentAPITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.config = self.root / "config"
        self.config.mkdir(mode=0o700)
        self.overrides = patch.dict(
            os.environ, {"PATENTSAR_CONFIG_DIR": str(self.config)}, clear=True
        )
        self.overrides.start()
        self.addCleanup(self.overrides.stop)
        self.origin = "http://127.0.0.1:18765"

    def client(self, mode="complete", timeout=10):
        app = create_app(
            self.root / "state",
            port=18765,
            analysis_settings=AnalysisSettings(),
            environment_storage=ManagedStorage(
                self.allowed, self.allowed / "managed", timeout
            ),
            environment_runner=BoundaryRunner(mode),
            environment_catalog=lambda: [dict(CARD)],
        )
        return TestClient(app, base_url=self.origin)

    def authenticate(self, client):
        session = client.get("/api/v1/session")
        self.assertEqual(session.status_code, 200)
        client.headers.update(
            {"Origin": self.origin, "X-CSRF-Token": session.json()["csrf_token"]}
        )

    def start(self, client, action="inspect", request_id="environment-request-1234"):
        return client.post(
            "/api/v1/environments/operations",
            json={
                "action": action,
                "component_ids": ["base"],
                "request_id": request_id,
                "expected_revision": 0,
            },
        )

    def completed(self, client, identifier):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = client.get("/api/v1/environments/operations/" + identifier).json()
            if value["status"] not in {"queued", "running"}:
                return value
            time.sleep(0.03)
        self.fail("Controlled owned worker did not finish within its test bound")

    def test_auth_csrf_input_and_location_never_start_an_install(self):
        with self.client() as client:
            self.assertEqual(client.get("/api/v1/environments").status_code, 401)
            client.get("/api/v1/session")
            self.assertEqual(self.start(client).status_code, 403)
            self.authenticate(client)
            for patch_value in (
                {"component_ids": ["arbitrary-package"]},
                {"command": "touch /tmp/forbidden"},
                {"expected_revision": False},
            ):
                body = {
                    "action": "install",
                    "component_ids": ["base"],
                    "request_id": "environment-request-1234",
                    "expected_revision": 0,
                    **patch_value,
                }
                self.assertEqual(
                    client.post(
                        "/api/v1/environments/operations", json=body
                    ).status_code,
                    422,
                )
            unsafe = client.put(
                "/api/v1/environments/settings",
                json={
                    "install_root": "/mnt/c/Users/Victor/unsafe",
                    "expected_revision": 0,
                },
            )
            self.assertEqual(unsafe.status_code, 400)
            self.assertEqual(
                client.get("/api/v1/environments").json()["operations"], []
            )
            self.assertFalse((self.allowed / "managed").exists())

    def test_missing_detection_real_persistence_and_idempotent_retry(self):
        with self.client() as client:
            self.authenticate(client)
            operation = self.start(client)
            self.assertEqual(operation.status_code, 202, operation.text)
            identifier = operation.json()["id"]
            value = self.completed(client, identifier)
            self.assertEqual(value["status"], "complete", value)
            self.assertFalse(value["applied"])
            catalog = client.get("/api/v1/environments").json()
            self.assertEqual(catalog["components"][0]["status"], "missing")
            self.assertIsNotNone(catalog["checked_at"])
            duplicate = self.start(client)
            self.assertEqual(duplicate.json()["id"], identifier)
            self.assertFalse((self.allowed / "managed").exists())
        with self.client() as client:
            self.authenticate(client)
            self.assertEqual(
                client.get("/api/v1/environments/operations/" + identifier).json()[
                    "status"
                ],
                "complete",
            )

    def test_verified_activation_and_failure_do_not_fake_success(self):
        with self.client() as client:
            self.authenticate(client)
            operation = self.start(client, action="install")
            value = self.completed(client, operation.json()["id"])
            self.assertEqual(value["status"], "complete", value)
            self.assertTrue(value["applied"])
            self.assertEqual(
                client.get("/api/v1/environments").json()["components"][0]["status"],
                "ready",
            )
            self.assertTrue((self.config / "env_paths.local.yaml").is_file())
        before = (self.config / "env_paths.local.yaml").read_bytes()
        with self.client(mode="fail") as client:
            self.authenticate(client)
            failed = self.start(
                client, action="install", request_id="environment-failed-1234"
            )
            value = self.completed(client, failed.json()["id"])
            self.assertEqual(value["status"], "failed", value)
            self.assertFalse(value["applied"])
            self.assertEqual(value["error"]["code"], "environment_install_failed")
        self.assertEqual((self.config / "env_paths.local.yaml").read_bytes(), before)

    def test_cancel_and_timeout_terminate_only_the_owned_operation(self):
        for mode in ("cancel", "timeout"):
            with (
                self.subTest(mode=mode),
                self.client(
                    mode="wait", timeout=0.2 if mode == "timeout" else 10
                ) as client,
            ):
                self.authenticate(client)
                operation = self.start(
                    client, request_id="environment-" + mode + "-1234"
                )
                identifier = operation.json()["id"]
                if mode == "cancel":
                    response = client.post(
                        "/api/v1/environments/operations/" + identifier + "/cancel",
                        json={},
                    )
                    self.assertEqual(response.status_code, 200)
                value = self.completed(client, identifier)
                self.assertEqual(
                    value["status"],
                    "cancelled" if mode == "cancel" else "failed",
                    value,
                )
                self.assertFalse(value["applied"])
        self.assertFalse((self.config / "env_paths.local.yaml").exists())


if __name__ == "__main__":
    unittest.main()
