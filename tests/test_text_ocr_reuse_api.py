"""Real authenticated API, SQLite, owned worker and copy; native SDK is controlled."""

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from patent_sar_extractor.paths import PACKAGE_IMPORT_ROOT
from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.environment_paths import ManagedStorage
from patent_sar_extractor.web.environment_specs import component_catalog
from patent_sar_extractor.web.processes import SubprocessRunner

WORKER = r"""
import json, sys, threading
from pathlib import Path
from patent_sar_extractor.web.environment_models import EnvironmentComponent
from patent_sar_extractor.web.environment_specs import component_catalog
from patent_sar_extractor.workers.environment_plan import read_plan, wait_for_owner
from patent_sar_extractor.workers.environment_recipes import EnvironmentProvisioner
from patent_sar_extractor.workers import text_ocr_reuse
root, model_spec = Path(sys.argv[1]), json.loads(sys.argv[2])
plan = read_plan(root / 'environment-plan.json')
cancel = threading.Event()
wait_for_owner(plan, cancel)
text_ocr_reuse.recipe = lambda: model_spec
def inspect(ids, context, **kwargs):
    cards = {c['id']:c for c in component_catalog()}
    return [EnvironmentComponent.model_validate({**cards[key], 'status':'ready',
      'location':context.bindings()[key], 'detected_version':'controlled-native-boundary',
      'checks':[{'name':'controlled','ok':True,'message':'Not an SDK or accuracy claim'}]}) for key in ids]
def forbidden(*args, **kwargs):
    raise AssertionError('No install/download fallback is permitted')
EnvironmentProvisioner.install = forbidden
from patent_sar_extractor.workers import environment_assets
environment_assets.download = forbidden
result = EnvironmentProvisioner(plan, cancel, inspect).execute()
(root / 'environment-result.json').write_text(json.dumps(result))
"""


class ReuseBoundaryRunner(SubprocessRunner):
    def __init__(self, spec):
        super().__init__()
        self.model_spec = spec

    def command(self, spec):
        return [
            sys.executable,
            "-c",
            WORKER,
            spec.output_dir,
            json.dumps(self.model_spec),
        ]

    def environment(self, spec):
        return {**super().environment(spec), "PYTHONPATH": str(PACKAGE_IMPORT_ROOT)}


class ExistingTextOCRReuseAPITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            dir=os.environ.get("PATENTSAR_WEB_TEST_ROOT")
        )
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "config"
        self.config.mkdir(mode=0o700)
        self.overrides = patch.dict(
            os.environ, {"PATENTSAR_CONFIG_DIR": str(self.config)}, clear=False
        )
        self.overrides.start()
        self.addCleanup(self.overrides.stop)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.models = self.root / "existing-models"
        self.models.mkdir()
        raw = b"bounded controlled model; not scientific data"
        (self.models / "weights.bin").write_bytes(raw)
        self.spec = {
            "models": [
                {
                    "file": "weights.bin",
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            ]
        }
        self.origin = "http://127.0.0.1:18765"
        self.body = {
            "action": "reuse",
            "component_ids": ["text-ocr", "text-ocr-models"],
            "reuse_source": {"python": sys.executable, "models": str(self.models)},
            "expected_revision": 0,
            "request_id": "reuse-controlled-source-1234",
        }
        (self.config / "env_paths.local.yaml").write_text(
            "paddleocr_mode: off\ncustom_operator_setting: preserve\n"
        )
        (self.config / "env_paths.local.yaml").chmod(0o600)

    def client(self):
        return TestClient(
            create_app(
                self.root / "state",
                port=18765,
                analysis_settings=AnalysisSettings(),
                environment_storage=ManagedStorage(
                    self.allowed, self.allowed / "managed", 10
                ),
                environment_runner=ReuseBoundaryRunner(self.spec),
                environment_catalog=component_catalog,
            ),
            base_url=self.origin,
        )

    def auth(self, client):
        reply = client.get("/api/v1/session")
        client.headers.update(
            {"Origin": self.origin, "X-CSRF-Token": reply.json()["csrf_token"]}
        )

    def wait(self, client, identifier):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            reply = client.get("/api/v1/environments/operations/" + identifier)
            self.assertEqual(reply.status_code, 200)
            if reply.json()["status"] not in {"queued", "running"}:
                return reply.json()
            time.sleep(0.03)
        self.fail("Owned controlled reuse did not finish")

    def test_authenticated_pair_copy_activation_and_reload_use_the_one_queue(self):
        with self.client() as client:
            self.assertEqual(
                client.post(
                    "/api/v1/environments/operations", json=self.body
                ).status_code,
                401,
            )
            client.get("/api/v1/session")
            self.assertEqual(
                client.post(
                    "/api/v1/environments/operations", json=self.body
                ).status_code,
                403,
            )
            self.auth(client)
            submitted = client.post("/api/v1/environments/operations", json=self.body)
            self.assertEqual(submitted.status_code, 202, submitted.text)
            self.assertEqual(
                submitted.json()["reuse_source"], self.body["reuse_source"]
            )
            result = self.wait(client, submitted.json()["id"])
            self.assertEqual(result["status"], "complete", result)
            self.assertTrue(result["applied"])
            duplicate = client.post("/api/v1/environments/operations", json=self.body)
            self.assertEqual(duplicate.json()["id"], result["id"])
            changed = {
                **self.body,
                "reuse_source": {**self.body["reuse_source"], "models": str(self.root)},
            }
            self.assertEqual(
                client.post(
                    "/api/v1/environments/operations", json=changed
                ).status_code,
                409,
            )
            saved = yaml.safe_load((self.config / "env_paths.local.yaml").read_text())
            self.assertEqual(saved["paddleocr_mode"], "on_demand")
            self.assertEqual(saved["paddleocr"], sys.executable)
            self.assertEqual(saved["custom_operator_setting"], "preserve")
            self.assertTrue(
                Path(saved["paddleocr_models"]).is_relative_to(self.allowed)
            )
            self.assertEqual(
                (Path(saved["paddleocr_models"]) / "weights.bin").read_bytes(),
                (self.models / "weights.bin").read_bytes(),
            )
        with self.client() as client:
            self.auth(client)
            catalog = client.get("/api/v1/environments").json()
            self.assertEqual(
                catalog["operations"][0]["reuse_source"], self.body["reuse_source"]
            )
            self.assertTrue(catalog["operations"][0]["applied"])

    def test_changed_local_weight_fails_without_configuration_publication(self):
        (self.models / "weights.bin").write_bytes(b"wrong")
        before = (self.config / "env_paths.local.yaml").read_bytes()
        with self.client() as client:
            self.auth(client)
            submitted = client.post("/api/v1/environments/operations", json=self.body)
            self.assertEqual(submitted.status_code, 202, submitted.text)
            result = self.wait(client, submitted.json()["id"])
            self.assertEqual(result["status"], "failed", result)
            self.assertFalse(result["applied"])
            self.assertEqual(
                (self.config / "env_paths.local.yaml").read_bytes(), before
            )
