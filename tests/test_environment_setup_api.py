"""Full plan uses one durable operation and one all-or-nothing publication."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from test_environment_api import BoundaryRunner, EnvironmentAPITests

from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.environment_paths import ManagedStorage
from patent_sar_extractor.web.environment_specs import (
    complete_components,
    component_catalog,
)

COMPLETE_WORKER = r"""
import json, sys, time
from pathlib import Path
root=Path(sys.argv[1]); plan=json.loads((root/'environment-plan.json').read_text())
while not (root/'environment-owner.json').exists(): time.sleep(.01)
cards=json.loads(sys.argv[3]); reports=[]; bindings={}
for identifier in plan['component_ids']:
    card=next(c for c in cards if c['id']==identifier)
    ready=not(sys.argv[2]=='reject' and identifier=='admet-models')
    location=plan['bindings'][identifier]
    card.update(status='ready' if ready else 'incompatible',location=location,detected_version='controlled-probe',
                checks=[{'name':'controlled-boundary','ok':ready,'message':'not actual SDK evidence'}])
    if sys.argv[2]=='false-proof' and identifier=='admet-models':
        card['checks'].append({'name':'failed-proof','ok':False,'message':'not promotable'})
    reports.append(card); bindings[identifier]=location
(root/'environment-result.json').write_text(json.dumps({'schema_version':1,'operation_id':plan['operation_id'],
                                                       'components':reports,'bindings':bindings}))
"""


class FullPlanRunner(BoundaryRunner):
    def command(self, spec):
        return [
            sys.executable,
            "-c",
            COMPLETE_WORKER,
            spec.output_dir,
            self.mode,
            json.dumps(component_catalog()),
        ]


class CompleteEnvironmentAPITests(EnvironmentAPITests):
    # Reuse authenticated real-SQLite/owned-child harness, not its unrelated cases.
    def full_client(self, mode="complete"):
        models = self.root / "existing-models"
        models.mkdir(exist_ok=True)
        config = {
            "environment_installer": sys.executable,
            "base": sys.executable,
            "decimer": sys.executable,
            "admet": sys.executable,
            "decimer_models": str(models),
            "admet_models": str(models),
            "molscribe": sys.executable,
            "molscribe_models": str(models),
        }
        self.config.joinpath("env_paths.local.yaml").write_text(yaml.safe_dump(config))
        self.config.joinpath("env_paths.local.yaml").chmod(0o600)
        app = create_app(
            self.root / "state",
            port=18765,
            analysis_settings=AnalysisSettings(
                admet_python=Path(sys.executable),
                admet_model_dir=models,
                decimer_python=Path(sys.executable),
                pystow_home=models,
            ),
            environment_storage=ManagedStorage(self.allowed, self.allowed / "managed"),
            environment_runner=FullPlanRunner(mode),
        )
        return TestClient(app, base_url=self.origin)

    def test_single_request_covers_all_dependencies_and_publishes_once(self):
        with self.full_client() as client:
            self.authenticate(client)
            catalog = client.get("/api/v1/environments").json()
            self.assertEqual(catalog["setup_component_ids"], complete_components())
            response = client.post(
                "/api/v1/environments/operations",
                json={
                    "action": "install",
                    "component_ids": catalog["setup_component_ids"],
                    "request_id": "complete-setup-request-1234",
                    "expected_revision": catalog["settings"]["revision"],
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            value = self.completed(client, response.json()["id"])
            self.assertEqual(value["status"], "complete", value)
            self.assertTrue(value["applied"])
            self.assertEqual(value["completed_components"], complete_components())
            final = client.get("/api/v1/environments").json()
            self.assertEqual(len(final["operations"]), 1)
            self.assertTrue(
                all(
                    c["status"] == "ready" and c["verification"] == "current"
                    for c in final["components"]
                )
            )
            self.assertEqual(
                len(list((self.config / ".environment-backups").iterdir())), 1
            )
            duplicate = client.post(
                "/api/v1/environments/operations",
                json={
                    "action": "install",
                    "component_ids": complete_components(),
                    "request_id": "complete-setup-request-1234",
                    "expected_revision": 0,
                },
            )
            self.assertEqual(duplicate.json()["id"], value["id"])
            self.assertEqual(
                len(client.get("/api/v1/environments").json()["operations"]), 1
            )

    def test_any_failed_component_keeps_prior_configuration_whole(self):
        with self.full_client(mode="reject") as client:
            before = self.config.joinpath("env_paths.local.yaml").read_bytes()
            self.authenticate(client)
            response = client.post(
                "/api/v1/environments/operations",
                json={
                    "action": "install",
                    "component_ids": complete_components(),
                    "request_id": "complete-rejected-request-1234",
                    "expected_revision": 0,
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            value = self.completed(client, response.json()["id"])
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["error"]["code"], "environment_verification")
            self.assertFalse(value["applied"])
            self.assertEqual(
                self.config.joinpath("env_paths.local.yaml").read_bytes(), before
            )
            self.assertFalse((self.config / ".environment-backups").exists())

    def test_ready_status_cannot_hide_one_failed_check_in_full_activation(self):
        with self.full_client(mode="false-proof") as client:
            before = self.config.joinpath("env_paths.local.yaml").read_bytes()
            self.authenticate(client)
            response = client.post(
                "/api/v1/environments/operations",
                json={
                    "action": "install",
                    "component_ids": complete_components(),
                    "request_id": "complete-false-proof-1234",
                    "expected_revision": 0,
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            value = self.completed(client, response.json()["id"])
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["error"]["code"], "environment_result")
            self.assertFalse(value["applied"])
            self.assertEqual(
                self.config.joinpath("env_paths.local.yaml").read_bytes(), before
            )


# The shared harness's methods are not this file's suite; select only the three new
# full-setup behaviors when loaded by unittest, avoiding duplicate/broad execution.
def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames(
        [
            __name__
            + ".CompleteEnvironmentAPITests.test_single_request_covers_all_dependencies_and_publishes_once",
            __name__
            + ".CompleteEnvironmentAPITests.test_any_failed_component_keeps_prior_configuration_whole",
            __name__
            + ".CompleteEnvironmentAPITests.test_ready_status_cannot_hide_one_failed_check_in_full_activation",
        ]
    )
