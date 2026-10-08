"""Inspect only the two affected version/CI workflows and their trust boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    # BaseLoader preserves GitHub's YAML 1.2 'on' key instead of YAML 1.1 booleans.
    return yaml.load(
        (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )


class ReleaseWorkflowTests(unittest.TestCase):
    def test_automation_never_runs_privileged_pr_checkout_or_artifacts(self):
        value = workflow("version.yml")
        self.assertNotIn("pull_request_target", value["on"])
        self.assertEqual(value["on"]["workflow_run"]["workflows"], ["ci"])
        self.assertEqual(value["permissions"], {})
        steps = value["jobs"]["prepare"]["steps"]
        checkout = steps[0]
        self.assertEqual(checkout["with"]["ref"], "main")
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        self.assertEqual(
            [step["run"] for step in steps if "run" in step],
            ["python tools/prepare_pr_version.py"],
        )
        self.assertFalse(
            any("download-artifact" in step.get("uses", "") for step in steps)
        )
        self.assertEqual(
            value["jobs"]["prepare"]["permissions"],
            {"contents": "write", "pull-requests": "read", "actions": "write"},
        )

    def test_ci_version_check_precedes_dependencies_and_stays_read_only(self):
        value = workflow("ci.yml")
        self.assertEqual(value["permissions"], {"contents": "read"})
        self.assertIn("workflow_dispatch", value["on"])
        steps = value["jobs"]["test"]["steps"]
        runs = [step.get("run", "") for step in steps]
        check = next(
            i for i, text in enumerate(runs) if "tools/pr_version.py --base" in text
        )
        install = next(i for i, text in enumerate(runs) if "uv sync --frozen" in text)
        self.assertLess(check, install)
        checkout = next(
            step for step in steps if "actions/checkout@" in step.get("uses", "")
        )
        self.assertEqual(checkout["with"]["fetch-depth"], "0")
        self.assertFalse(any("unittest discover" in text for text in runs))
        prepare = next(
            text for text in runs if "tools/prepare_browser_fixture.py" in text
        )
        self.assertIn("--read-only", prepare)
        self.assertIn("product-version.spec.ts", prepare)


if __name__ == "__main__":
    unittest.main()
