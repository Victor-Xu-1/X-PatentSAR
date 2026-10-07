"""Eight-component contracts and injected dispatch only; no native SDK/network."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_environment_recipes as recipe_tests
import yaml
from pydantic import ValidationError

from patent_sar_extractor.web import environment_specs
from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.environment_config import EnvironmentConfig
from patent_sar_extractor.web.environment_inspection import (
    InspectionContext,
    inspect_components,
)
from patent_sar_extractor.web.environment_models import EnvironmentOperationRequest
from patent_sar_extractor.web.environment_queue import EnvironmentQueue
from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.environments import EnvironmentManager
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.processes import RunSpec
from patent_sar_extractor.workers.environment_files import atomic_json

ALL_IDS = [
    "installer",
    "base",
    "decimer",
    "decimer-models",
    "admet",
    "admet-models",
    "molscribe",
    "molscribe-models",
]
MOLSCRIBE_IDS = ALL_IDS[-2:]


class WiringFixture(recipe_tests.RecipeFixture):
    def setUp(self):
        super().setUp()
        self.models = self.root / "controlled-model-directory"
        self.models.mkdir()
        self.recipe = self.root / "molscribe-runtime.json"
        self.recipe.write_text("{}")
        # Native specs/recipes belong to the parent. Inject their contract shape,
        # not a competing production catalog or real model/probe implementation.
        specs = tuple(
            spec
            for spec in environment_specs.component_specs()
            if spec.id not in MOLSCRIBE_IDS
        ) + tuple(
            environment_specs.ComponentSpec(
                id=identifier,
                name=identifier,
                description="Controlled wiring input, not native verification",
                version="pinned-by-parent",
                kind="runtime" if identifier == "molscribe" else "models",
                group="structure",
                required=False,
                license="controlled-test",
                source_url="https://example.invalid/molscribe",
                dependencies=("installer",)
                if identifier == "molscribe"
                else ("molscribe",),
            )
            for identifier in MOLSCRIBE_IDS
        )
        self.specs = patch.object(environment_specs, "_SPECS", specs)
        self.specs.start()
        self.addCleanup(self.specs.stop)
        self.cards = environment_specs.component_catalog()
        self.bindings = {
            identifier: str(self.models)
            if identifier.endswith("-models")
            else sys.executable
            for identifier in ALL_IDS
        }

    def reports(self):
        return [
            {
                **card,
                "status": "ready",
                "location": self.bindings[card["id"]],
                "detected_version": "controlled-observed-version",
                "checks": [
                    {"name": "injected", "ok": True, "message": "not SDK proof"}
                ],
            }
            for card in self.cards
        ]


class MolScribeContractTests(WiringFixture):
    def test_all_eight_request_and_schema_keep_optional_structure_components(self):
        request = EnvironmentOperationRequest(
            action="install",
            component_ids=ALL_IDS,
            request_id="controlled-eight-request",
            expected_revision=0,
        )
        self.assertEqual(request.component_ids, ALL_IDS)
        schema = EnvironmentOperationRequest.model_json_schema()["properties"][
            "component_ids"
        ]
        self.assertEqual(schema["maxItems"], 8)
        self.assertEqual(set(schema["items"]["enum"]), set(ALL_IDS))
        optional = [card for card in self.cards if card["id"] in MOLSCRIBE_IDS]
        self.assertEqual([card["kind"] for card in optional], ["runtime", "models"])
        self.assertTrue(all(not card["required"] for card in optional))
        self.assertTrue(all(card["group"] == "structure" for card in optional))
        self.assertEqual(environment_specs.complete_components(), ALL_IDS)

    def test_unknown_duplicate_or_ninth_component_is_rejected(self):
        for ids in (ALL_IDS + ["cuda"], ALL_IDS + ["base"], ["molscribe"] * 2):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                EnvironmentOperationRequest(
                    action="inspect",
                    component_ids=ids,
                    request_id="controlled-invalid-request",
                    expected_revision=0,
                )

    def test_context_round_trips_eight_captured_bindings_and_rejects_unknown(self):
        context = InspectionContext.from_bindings(self.bindings)
        self.assertEqual(context.bindings(), self.bindings)
        with self.assertRaises(ValueError):
            InspectionContext.from_bindings({**self.bindings, "cuda": None})
        with self.assertRaises(ValueError):
            InspectionContext.from_bindings(
                {**self.bindings, "molscribe-models": "relative"}
            )


class MolScribeDispatchTests(WiringFixture):
    def probe(self, response, ids=None, **kwargs):
        runner = Mock()
        if isinstance(response, BaseException):
            runner.run.side_effect = response
        else:
            runner.run.return_value = response
        with (
            patch(
                "patent_sar_extractor.web.environment_inspection.BoundedAnalysisRunner",
                return_value=runner,
            ),
            patch(
                "patent_sar_extractor.web.environment_inspection.recipe_path",
                return_value=self.recipe,
            ) as recipe,
        ):
            try:
                reports = inspect_components(
                    ids or MOLSCRIBE_IDS,
                    InspectionContext.from_bindings(self.bindings),
                    op_dir=self.operation,
                    **kwargs,
                )
            finally:
                runner.close.assert_called_once_with()
        return reports, runner, recipe

    @staticmethod
    def response(**changes):
        return {
            "ok": True,
            "version": "controlled-native-version",
            "checks": [{"name": "native", "ok": True, "message": "injected only"}],
            **changes,
        }

    def test_existing_carrier_receives_roles_recipe_model_root_and_cancel(self):
        cancel = threading.Event()
        reports, runner, recipe = self.probe(self.response(), cancel=cancel)
        self.assertEqual([report.id for report in reports], MOLSCRIBE_IDS)
        self.assertTrue(all(report.status == "ready" for report in reports))
        self.assertTrue(
            all(
                report.detected_version == "controlled-native-version"
                for report in reports
            )
        )
        self.assertEqual(runner.run.call_count, 2)
        for identifier, call in zip(MOLSCRIBE_IDS, runner.run.call_args_list):
            self.assertEqual(call.args[0][0], sys.executable)
            self.assertTrue(call.args[0][-1].endswith("environment_probe_worker.py"))
            self.assertEqual(
                call.args[1],
                {
                    "role": identifier,
                    "recipe": str(self.recipe),
                    "model_root": str(self.models),
                },
            )
            self.assertEqual(call.kwargs["timeout"], 180)
            self.assertIs(call.kwargs["cancel"], cancel)
        self.assertEqual(recipe.call_count, 2)
        recipe.assert_called_with("molscribe-runtime.json")

    def test_failed_or_malformed_native_result_never_claims_ready(self):
        for response in (
            self.response(ok=False),
            self.response(ok="true"),
            self.response(version=None),
            self.response(version=""),
            self.response(checks=[]),
        ):
            with self.subTest(response=response):
                reports, _, _ = self.probe(response)
                self.assertTrue(all(report.status != "ready" for report in reports))

    def test_unconfigured_models_and_infrastructure_failure_do_not_install_or_hide(
        self,
    ):
        self.bindings["molscribe-models"] = None
        reports, runner, _ = self.probe(self.response(), ids=["molscribe-models"])
        self.assertEqual(reports[0].status, "unconfigured")
        runner.run.assert_not_called()
        before = tuple(self.models.iterdir())
        reports, runner, _ = self.probe(
            WebError(503, "analysis_memory", "controlled failure"), ids=["molscribe"]
        )
        self.assertEqual(reports[0].status, "error")
        self.assertIsNone(reports[0].detected_version)
        self.assertEqual(runner.run.call_count, 1)
        self.assertEqual(tuple(self.models.iterdir()), before)

    def test_cancellation_propagates_and_closes_only_injected_carrier(self):
        with self.assertRaises(WebError) as caught:
            self.probe(WebError(503, "analysis_cancelled", "controlled cancellation"))
        self.assertEqual(caught.exception.code, "analysis_cancelled")


class MolScribeDurableWiringTests(WiringFixture):
    def test_private_plan_captures_all_eight_and_rejects_missing_or_unknown_binding(
        self,
    ):
        plan = self.plan(component_ids=ALL_IDS, bindings=self.bindings)
        self.assertEqual(plan.component_ids, ALL_IDS)
        self.assertEqual(plan.bindings, self.bindings)
        for bindings in (
            {key: value for key, value in self.bindings.items() if key != "molscribe"},
            {**self.bindings, "cuda": None},
        ):
            with self.subTest(bindings=bindings), self.assertRaises(ValueError):
                self.plan(component_ids=ALL_IDS, bindings=bindings)

    def test_queue_accepts_eight_progress_and_reports_but_not_duplicate_progress(self):
        queue = EnvironmentQueue(Mock(), Mock(), 10, Mock())
        spec = RunSpec(
            self.identifier,
            "environment",
            "",
            str(self.operation),
            "environment",
            "test",
        )
        atomic_json(
            self.operation,
            "environment-progress.json",
            {"stage": "controlled", "completed_components": ALL_IDS},
            limit=65536,
        )
        queue._progress(spec)
        self.assertEqual(
            json.loads(queue.store.update.call_args.kwargs["completed_components"]),
            ALL_IDS,
        )
        value = {
            "schema_version": 1,
            "operation_id": self.identifier,
            "components": self.reports(),
            "bindings": self.bindings,
        }
        atomic_json(self.operation, "environment-result.json", value, limit=512 * 1024)
        self.assertEqual(
            queue._result(spec, {"action": "install", "component_ids": ALL_IDS}), value
        )
        atomic_json(
            self.operation,
            "environment-progress.json",
            {"stage": "controlled", "completed_components": ["molscribe"] * 2},
            limit=65536,
        )
        with self.assertRaises(WebError):
            queue._progress(spec)

    def test_report_storage_retains_all_eight_with_fixed_overflow_bound(self):
        store = EnvironmentStore(self.root / "state", self.install)
        store.publish_reports("controlled-source", self.reports())
        self.assertEqual(set(store.report_records()), set(ALL_IDS))
        with store.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO components VALUES(?,?,?)",
                ("cuda", "controlled-source", '{"id":"cuda"}'),
            )
        with self.assertRaises(WebError):
            store.report_records()

    def test_complete_catalog_and_dependency_resolution_use_parent_spec_authority(self):
        config = Mock()
        config.bindings.return_value = self.bindings
        config.fingerprint.return_value = "controlled-config"
        manager = EnvironmentManager(
            self.root / "state",
            SimpleNamespace(settings=AnalysisSettings()),
            lambda: self.cards,
            config=config,
        )
        self.assertEqual(manager.resolve_components(ALL_IDS), ALL_IDS)
        self.assertEqual(
            manager.resolve_components(["molscribe-models"]),
            ["installer", "molscribe", "molscribe-models"],
        )
        catalog = manager.catalog()
        self.assertEqual(catalog.setup_component_ids, ALL_IDS)
        self.assertEqual(
            next(p.component_ids for p in catalog.presets if p.id == "extraction"),
            ALL_IDS,
        )

    def test_verified_runtime_still_requires_executable_and_no_false_ready_check(self):
        manager = object.__new__(EnvironmentManager)
        plan = {
            "install_root": str(self.install),
            "component_ids": MOLSCRIBE_IDS,
            "bindings": self.bindings,
        }
        reports = [report for report in self.reports() if report["id"] in MOLSCRIBE_IDS]
        result = {
            "bindings": {key: self.bindings[key] for key in MOLSCRIBE_IDS},
            "components": reports,
        }
        self.assertEqual(manager._verified_bindings(plan, result), result["bindings"])
        reports[0]["checks"][0]["ok"] = False
        with self.assertRaises(WebError):
            manager._verified_bindings(plan, result)
        reports[0]["checks"][0]["ok"] = True
        path = self.install / "non-executable"
        path.write_text("controlled input")
        result["bindings"]["molscribe"] = str(path)
        reports[0]["location"] = str(path)
        with self.assertRaises(WebError):
            manager._verified_bindings(plan, result)

    def test_config_publishes_only_known_molscribe_keys_preserving_operator_fields(
        self,
    ):
        root = self.root / "config"
        root.mkdir()
        config = EnvironmentConfig(root)
        path = root / config.name
        path.write_text(yaml.safe_dump({"operator_field": "preserve"}))
        path.chmod(0o600)
        with patch.dict(os.environ, {"PATENTSAR_CONFIG_DIR": str(root)}, clear=True):
            config.publish(
                self.identifier,
                config.fingerprint(),
                {key: self.bindings[key] for key in MOLSCRIBE_IDS},
            )
        saved = yaml.safe_load(path.read_text())
        self.assertEqual(saved["molscribe"], sys.executable)
        self.assertEqual(saved["molscribe_models"], str(self.models))
        self.assertEqual(saved["operator_field"], "preserve")

    def test_bindings_use_shared_runtime_role_and_explicit_model_override(self):
        config = EnvironmentConfig(self.root / "config")
        with (
            patch(
                "patent_sar_extractor.web.environment_config.get_python",
                return_value=sys.executable,
            ) as role,
            patch(
                "patent_sar_extractor.web.environment_config.ENV_ROLES",
                ("base", "decimer", "molscribe"),
            ),
            patch.dict(os.environ, {"PATENTSAR_MOLSCRIBE_MODEL_DIR": str(self.models)}),
        ):
            bindings = config.bindings(AnalysisSettings())
        self.assertEqual(bindings["molscribe"], sys.executable)
        self.assertEqual(bindings["molscribe-models"], str(self.models))
        self.assertIn(unittest.mock.call("molscribe"), role.call_args_list)

    def test_missing_native_role_stays_unconfigured_without_substitute_interpreter(
        self,
    ):
        config = EnvironmentConfig(self.root / "config")
        with (
            patch(
                "patent_sar_extractor.web.environment_config.ENV_ROLES",
                ("base", "decimer"),
            ),
            patch(
                "patent_sar_extractor.web.environment_config.get_python",
                return_value=sys.executable,
            ) as role,
            patch(
                "patent_sar_extractor.web.environment_config.configured_model_environment",
                return_value={},
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            bindings = config.bindings(AnalysisSettings())
        self.assertIsNone(bindings["molscribe"])
        self.assertIsNone(bindings["molscribe-models"])
        self.assertNotIn(unittest.mock.call("molscribe"), role.call_args_list)

    def test_saved_models_use_parent_shared_configuration_mapping(self):
        config = EnvironmentConfig(self.root / "config")
        with (
            patch(
                "patent_sar_extractor.web.environment_config.configured_model_environment",
                return_value={"PATENTSAR_MOLSCRIBE_MODEL_DIR": str(self.models)},
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(
                config.bindings(AnalysisSettings())["molscribe-models"],
                str(self.models),
            )


if __name__ == "__main__":
    unittest.main()
