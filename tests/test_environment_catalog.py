"""Cheap path presence, current proof and historical checks are distinct facts."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor.web.environment_paths import ManagedStorage
from patent_sar_extractor.web.environment_specs import component_catalog
from patent_sar_extractor.web.environments import EnvironmentManager
from patent_sar_extractor.web.errors import WebError


class CapturedConfig:
    def __init__(self, root):
        self.identity = "original-config"
        self.paths = {item["id"]: None for item in component_catalog()}
        self.paths["base"] = sys.executable
        self.paths["decimer-models"] = str(root / "models")

    def bindings(self, analysis):
        return dict(self.paths)

    def fingerprint(self):
        return self.identity


class EnvironmentCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.config = CapturedConfig(self.root)
        self.recipe = "recipe-one"
        self.manager = EnvironmentManager(
            self.root / "state",
            SimpleNamespace(settings=None),
            component_catalog,
            config=self.config,
            recipe_identity=lambda: self.recipe,
            storage=ManagedStorage(self.allowed, self.allowed / "managed"),
        )

    def card(self, identifier="base", **values):
        item = next(i for i in component_catalog() if i["id"] == identifier)
        return {
            **item,
            "status": "ready",
            "location": self.config.paths[identifier],
            "detected_version": "measured-version",
            "checks": [{"name": "controlled-probe", "ok": True, "message": "fixture"}],
            **values,
        }

    def components(self):
        return {c.id: c for c in self.manager.catalog().components}

    def test_uncached_catalog_reads_configured_paths_without_running_probes(self):
        with patch(
            "subprocess.Popen", side_effect=AssertionError("GET launched a child")
        ):
            components = self.components()
        base = components["base"]
        self.assertEqual(base.location, sys.executable)
        self.assertEqual(base.presence, "present")
        self.assertEqual(base.status, "unchecked")
        self.assertEqual(base.verification, "unchecked")
        self.assertIsNone(base.detected_version)
        self.assertEqual(base.checks, [])
        self.assertEqual(components["decimer-models"].presence, "missing")
        self.assertEqual(components["decimer-models"].status, "missing")
        self.assertEqual(components["installer"].presence, "unconfigured")
        self.assertEqual(components["installer"].status, "unconfigured")
        self.assertEqual(self.manager.store.history(), [])
        self.assertFalse((self.allowed / "managed").exists())

    def test_stale_report_survives_as_history_not_current_ready(self):
        self.manager.store.publish_reports(self.manager._source_key(), [self.card()])
        checked_at = self.components()["base"].checked_at
        self.assertIsNotNone(checked_at)
        self.recipe = "recipe-two"
        base = self.components()["base"]
        self.assertEqual(
            (base.presence, base.status, base.verification),
            ("present", "unchecked", "stale"),
        )
        self.assertEqual(base.location, sys.executable)
        self.assertIsNone(base.detected_version)
        self.assertEqual(base.checks, [])
        self.assertIsNone(base.checked_at)
        self.assertEqual(base.last_check.detected_version, "measured-version")
        self.assertEqual(base.last_check.checked_at, checked_at)
        self.assertIsNotNone(self.manager.catalog().checked_at)

    def test_old_sqlite_report_has_unknown_individual_time_not_fake_global_time(self):
        from patent_sar_extractor.web.storage import encode

        with self.manager.store.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO components VALUES(?,?,?)",
                ("base", "historical-source", encode(self.card())),
            )
            connection.execute(
                "UPDATE settings SET checked_at='legacy-latest' WHERE id=1"
            )
        base = self.components()["base"]
        self.assertEqual(base.verification, "stale")
        self.assertIsNone(base.last_check.checked_at)
        self.assertEqual(self.manager.catalog().checked_at, "legacy-latest")

    def test_changed_path_never_inherits_old_version_or_checks(self):
        self.manager.store.publish_reports(self.manager._source_key(), [self.card()])
        self.config.paths["base"] = str(self.root / "other-python")
        base = self.components()["base"]
        self.assertEqual(base.location, self.config.paths["base"])
        self.assertEqual((base.status, base.presence), ("missing", "missing"))
        self.assertIsNone(base.last_check)
        self.assertIsNone(base.detected_version)

    def test_deleted_path_cannot_remain_cached_ready(self):
        models = self.root / "models"
        models.mkdir()
        self.manager.store.publish_reports(
            self.manager._source_key(), [self.card("decimer-models")]
        )
        self.assertEqual(self.components()["decimer-models"].status, "ready")
        models.rmdir()
        component = self.components()["decimer-models"]
        self.assertEqual((component.status, component.presence), ("missing", "missing"))
        self.assertEqual(component.verification, "stale")
        self.assertIsNone(component.detected_version)

    def test_actual_failed_check_stays_failed_and_partial_checks_keep_their_time(self):
        with patch(
            "patent_sar_extractor.web.environment_storage.now",
            return_value="first-check",
        ):
            self.manager.store.publish_reports(
                self.manager._source_key(), [self.card()]
            )
        with patch(
            "patent_sar_extractor.web.environment_storage.now",
            return_value="second-check",
        ):
            self.manager.store.publish_reports(
                self.manager._source_key(),
                [self.card("decimer-models", status="missing")],
            )
        components = self.components()
        self.assertEqual(components["base"].checked_at, "first-check")
        self.assertEqual(components["decimer-models"].checked_at, "second-check")
        self.manager.store.publish_reports(
            self.manager._source_key(),
            [
                self.card(
                    status="incompatible",
                    checks=[{"name": "version", "ok": False, "message": "different"}],
                )
            ],
        )
        base = self.components()["base"]
        self.assertEqual(
            (base.presence, base.verification, base.status),
            ("present", "current", "incompatible"),
        )

    def test_invalid_or_wrong_kind_bindings_never_claim_readiness(self):
        for location in ("relative", "bad\x00path", str(self.root)):
            with self.subTest(location=location):
                self.config.paths["base"] = location
                base = self.components()["base"]
                self.assertEqual(base.presence, "unknown")
                self.assertEqual(base.status, "error")
                self.assertIsNone(base.detected_version)
        original = Path.stat

        def stat_path(path, *args, **kwargs):
            if str(path) == sys.executable:
                raise PermissionError("private diagnostic")
            return original(path, *args, **kwargs)

        with patch("pathlib.Path.stat", stat_path):
            self.config.paths["base"] = sys.executable
            base = self.components()["base"]
        self.assertEqual((base.presence, base.status), ("unknown", "error"))
        self.assertNotIn("private diagnostic", base.problem)

    def test_inspection_result_cannot_be_published_under_changed_source(self):
        plan = {
            "action": "inspect",
            "source_key": self.manager._source_key(),
            "component_ids": ["base"],
            "bindings": self.config.bindings(None),
            "config_fingerprint": self.config.fingerprint(),
        }
        self.config.identity = "operator-edited"
        with self.assertRaises(WebError) as error:
            self.manager._completed(plan, {"components": [self.card()]})
        self.assertEqual(error.exception.code, "environment_inspection_changed")
        self.assertEqual(self.manager.store.report_records(), {})
        self.assertIsNone(self.manager.store.settings()["checked_at"])

    def test_current_inspection_publishes_same_path_and_fresh_individual_time(self):
        plan = {
            "action": "inspect",
            "source_key": self.manager._source_key(),
            "component_ids": ["base"],
            "bindings": self.config.bindings(None),
            "config_fingerprint": self.config.fingerprint(),
        }
        self.manager._completed(plan, {"components": [self.card()]})
        base = self.components()["base"]
        self.assertEqual(
            (base.presence, base.verification, base.status),
            ("present", "current", "ready"),
        )
        self.assertIsNotNone(base.checked_at)
        self.assertIsNone(base.last_check)

    def test_empty_or_failed_checks_cannot_claim_ready_from_saved_status_alone(self):
        for checks in ([], [{"name": "version", "ok": False, "message": "different"}]):
            with self.subTest(checks=checks):
                self.manager.store.publish_reports(
                    self.manager._source_key(), [self.card(checks=checks)]
                )
                self.assertEqual(self.components()["base"].status, "error")

    def test_changed_snapshot_is_rejected_instead_of_mixing_bindings_and_fingerprint(
        self,
    ):
        with patch.object(self.config, "fingerprint", side_effect=["before", "after"]):
            with self.assertRaises(WebError) as error:
                self.manager.catalog()
        self.assertEqual(error.exception.code, "environment_configuration_changed")


if __name__ == "__main__":
    unittest.main()
