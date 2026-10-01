"""Read-only acceptance regressions; contract fixtures are not extraction evidence."""

from __future__ import annotations

import copy
import unittest

from patent_sar_extractor import contracts
from patent_sar_extractor.web.acceptance import ARTIFACTS, authority


def complete_payloads():
    payloads = {
        name: contracts.artifact_identity(schema, version)
        for name, (_, schema, version) in ARTIFACTS.items()
    }
    payloads["summary"].update(status="complete", steps={})
    payloads["activity"].update(active_cpds=["Example 1"], rows=[])
    payloads["structures"]["structures"] = []
    payloads["bindings"].update(
        execution_mode="production_activity_led", final_bindings=[]
    )
    payloads["smiles"].update(execution_mode="production_decimer", records=[])
    payloads["qa"].update(ok=True, acceptance={"ok": True, "hard_errors": []})
    return payloads


def partial_payloads(status="running"):
    payloads = complete_payloads()
    for name in ("locator", "structures", "bindings", "smiles", "qa"):
        payloads[name] = None
    payloads["summary"].update(
        status=status,
        steps={"classify": {"status": "ok"}, "activity": {"status": "running"}},
    )
    return payloads


class AcceptanceTests(unittest.TestCase):
    def test_resumed_successful_stage_does_not_replay_a_previous_failure_as_current(
        self,
    ):
        payloads = partial_payloads()
        payloads["summary"]["steps"]["bind"] = {"status": "ok"}
        marker = {
            **contracts.artifact_identity(
                contracts.FAILURE_MARKER_SCHEMA, contracts.FAILURE_MARKER_SCHEMA_VERSION
            ),
            "stage": "bind",
            "errors": ["previous binding failure"],
        }
        result, _ = authority(payloads, pdf_verified=True, marker=marker)
        self.assertEqual(result.state, "not_run")
        self.assertNotIn("previous binding failure", str(result.errors))
        payloads["summary"]["steps"]["bind"] = {"status": "failed"}
        failed, _ = authority(payloads, pdf_verified=True, marker=marker)
        self.assertEqual(failed.state, "failed")
        self.assertIn("previous binding failure", failed.errors)

    def test_current_failure_marker_is_failed_not_historical_when_downstream_absent(
        self,
    ):
        marker = {
            **contracts.artifact_identity(
                contracts.FAILURE_MARKER_SCHEMA, contracts.FAILURE_MARKER_SCHEMA_VERSION
            ),
            "stage": "activity",
            "errors": ["Activity rows conflict before binding."],
        }
        result, historical = authority(
            partial_payloads("failed_accuracy_gate"), pdf_verified=True, marker=marker
        )
        self.assertEqual(result.state, "failed")
        self.assertFalse(historical)
        self.assertIn("Activity rows conflict before binding.", result.errors)

    def test_current_running_and_checkpointed_runs_are_not_historical_or_accepted(self):
        for status in ("running", "started", "classifying"):
            with self.subTest(status=status):
                result, historical = authority(
                    partial_payloads(status), pdf_verified=True, marker=None
                )
                self.assertEqual(result.state, "not_run")
                self.assertFalse(historical)
                self.assertTrue(result.errors)

    def test_summary_stage_failure_remains_failed_without_marker(self):
        payloads = partial_payloads()
        payloads["summary"]["steps"]["activity"] = {
            "status": "failed",
            "acceptance_errors": ["Ambiguous activity row at /private/patent.pdf."],
        }
        result, historical = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "failed")
        self.assertFalse(historical)
        self.assertIn("[path]", result.errors[0])
        self.assertNotIn("/private", str(result.errors))

    def test_missing_current_artifact_does_not_become_historical_or_accepted(self):
        for name in ARTIFACTS:
            with self.subTest(name=name):
                payloads = complete_payloads()
                payloads[name] = None
                result, historical = authority(payloads, pdf_verified=True, marker=None)
                self.assertNotEqual(result.state, "accepted")
                self.assertFalse(historical)

    def test_stale_or_unversioned_present_artifact_remains_historical(self):
        for name in ARTIFACTS:
            with self.subTest(name=name):
                payloads = complete_payloads()
                payloads[name]["ruleset"]["version"] = "0.0.0"
                result, historical = authority(payloads, pdf_verified=True, marker=None)
                self.assertEqual(result.state, "historical")
                self.assertTrue(historical)
        payloads["smiles"] = []
        result, historical = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "historical")
        self.assertTrue(historical)

    def test_current_invalid_shapes_or_modes_fail_without_historical_claim(self):
        for name, field, value in (
            ("activity", "rows", {}),
            ("activity", "active_cpds", []),
            ("bindings", "final_bindings", {}),
            ("bindings", "execution_mode", "diagnostic"),
            ("smiles", "records", {}),
            ("smiles", "execution_mode", "diagnostic"),
            ("structures", "structures", {}),
            ("summary", "steps", []),
        ):
            with self.subTest(name=name, field=field):
                payloads = complete_payloads()
                payloads[name][field] = value
                result, historical = authority(payloads, pdf_verified=True, marker=None)
                self.assertEqual(result.state, "failed")
                self.assertFalse(historical)

    def test_current_complete_run_requires_original_both_qa_checks_and_no_marker(self):
        baseline = complete_payloads()
        accepted, historical = authority(baseline, pdf_verified=True, marker=None)
        self.assertEqual(accepted.state, "accepted")
        self.assertFalse(historical)
        for field in ("ok", "acceptance"):
            payloads = copy.deepcopy(baseline)
            if field == "ok":
                payloads["qa"][field] = False
            else:
                payloads["qa"][field]["ok"] = False
            result, _ = authority(payloads, pdf_verified=True, marker=None)
            self.assertEqual(result.state, "failed")
        for marker in ({}, {"errors": "invalid"}, {"errors": ["traceback secret"]}):
            result, _ = authority(baseline, pdf_verified=True, marker=marker)
            self.assertEqual(result.state, "failed")
            self.assertNotIn("secret", str(result.errors))
        result, historical = authority(baseline, pdf_verified=False, marker=None)
        self.assertEqual(result.state, "failed")
        self.assertFalse(historical)

    def test_summary_failure_cannot_be_overridden_by_complete_qa_artifacts(self):
        payloads = complete_payloads()
        payloads["summary"]["status"] = "failed_accuracy_gate"
        result, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "failed")

    def test_current_running_summary_cannot_reuse_a_completed_qa_decision(self):
        payloads = complete_payloads()
        payloads["summary"]["status"] = "running"
        result, historical = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "not_run")
        self.assertFalse(historical)

    def test_empty_and_untrusted_failure_error_collections_remain_bounded(self):
        payloads = partial_payloads("failed_accuracy_gate")
        for errors in ([], "invalid", [None], ["Repeated failure"] * 1000):
            with self.subTest(errors_type=type(errors).__name__):
                result, _ = authority(
                    payloads, pdf_verified=True, marker={"errors": errors}
                )
                self.assertEqual(result.state, "failed")
                self.assertTrue(result.errors)
                self.assertLessEqual(len(result.errors), 100)
