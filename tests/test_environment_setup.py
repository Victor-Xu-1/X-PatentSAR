"""A complete setup is one fixed dependency plan, never six user-driven installs."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from test_environment_recipes import RecipeFixture

from patent_sar_extractor.web.environment_models import EnvironmentComponent
from patent_sar_extractor.web.environment_specs import (
    component_catalog,
    resolved_components,
)
from patent_sar_extractor.workers.environment_errors import EnvironmentFailure
from patent_sar_extractor.workers.environment_recipes import EnvironmentProvisioner


class CompleteEnvironmentSetupTests(RecipeFixture):
    def setUp(self):
        super().setUp()
        self.ids = [item["id"] for item in component_catalog()]

    def provisioner(self, missing=(), error=None, reject=None):
        self.events = []
        self.installed = set()

        def inspect(ids, context, **kwargs):
            identifier = ids[0]
            self.events.append(("inspect", identifier))
            card = next(c for c in component_catalog() if c["id"] == identifier)
            if identifier == error:
                status = "error"
            elif identifier in missing and (
                identifier not in self.installed or identifier == reject
            ):
                status = "missing"
            else:
                status = "ready"
            return [
                EnvironmentComponent.model_validate(
                    {
                        **card,
                        "status": status,
                        "location": context.bindings()[identifier],
                        "detected_version": "controlled-actual"
                        if status == "ready"
                        else None,
                        "checks": [
                            {
                                "name": "boundary",
                                "ok": status == "ready",
                                "message": "not real SDK evidence",
                            }
                        ],
                    }
                )
            ]

        bindings = {identifier: str(self.root / identifier) for identifier in self.ids}
        value = EnvironmentProvisioner(
            self.plan(action="install", component_ids=self.ids, bindings=bindings),
            threading.Event(),
            inspect,
        )

        def install(identifier):
            self.events.append(("install", identifier))
            self.installed.add(identifier)
            return self.install / ("new-" + identifier)

        value.install = install
        return value

    def test_complete_plan_includes_admet_and_models_even_if_optional_in_cli(self):
        from patent_sar_extractor.web.environment_specs import complete_components

        self.assertEqual(complete_components(), self.ids)
        self.assertEqual(resolved_components(complete_components()), self.ids)
        self.assertIn("admet-models", complete_components())

    def test_one_complete_execution_rechecks_reuses_and_installs_only_missing(self):
        worker = self.provisioner(missing={"installer", "admet-models"})
        with patch(
            "patent_sar_extractor.workers.environment_recipes.segmentation_config",
            return_value={},
        ):
            result = worker.execute()
        self.assertEqual(self.installed, {"installer", "admet-models"})
        self.assertEqual(
            [item[1] for item in self.events if item[0] == "install"],
            ["installer", "admet-models"],
        )
        self.assertEqual(worker.completed, self.ids)
        self.assertEqual(set(result["bindings"]), set(self.ids))
        self.assertTrue(all(c["status"] == "ready" for c in result["components"]))
        self.assertTrue(
            all(("inspect", identifier) in self.events for identifier in self.ids)
        )

    def test_all_ready_components_are_rechecked_without_installation(self):
        worker = self.provisioner()
        with patch(
            "patent_sar_extractor.workers.environment_recipes.segmentation_config",
            return_value={},
        ):
            worker.execute()
        self.assertEqual(self.installed, set())
        self.assertEqual(
            self.events, [("inspect", identifier) for identifier in self.ids]
        )

    def test_cold_complete_plan_uses_dependency_order_and_checks_every_new_component(
        self,
    ):
        worker = self.provisioner(missing=set(self.ids))
        with patch(
            "patent_sar_extractor.workers.environment_recipes.segmentation_config",
            return_value={},
        ):
            worker.execute()
        self.assertEqual(
            [item[1] for item in self.events if item[0] == "install"], self.ids
        )
        for identifier in self.ids:
            self.assertEqual(
                [event for event in self.events if event[1] == identifier],
                [
                    ("inspect", identifier),
                    ("install", identifier),
                    ("inspect", identifier),
                ],
            )

    def test_resource_or_probe_error_cannot_trigger_redundant_installation(self):
        worker = self.provisioner(error="base")
        with self.assertRaises(EnvironmentFailure):
            worker.execute()
        self.assertEqual(self.installed, set())
        self.assertEqual(worker.completed, ["installer"])

    def test_new_component_rejected_stops_complete_plan_before_activation(self):
        worker = self.provisioner(missing={"base"}, reject="base")
        with self.assertRaises(EnvironmentFailure) as error:
            worker.execute()
        self.assertEqual(error.exception.code, "verification_failed")
        self.assertEqual(worker.completed, ["installer"])
        self.assertEqual(self.installed, {"base"})
        self.assertFalse((self.operation / "environment-result.json").exists())


if __name__ == "__main__":
    unittest.main()
