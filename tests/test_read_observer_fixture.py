"""Read-observer acceptance never inherits an execution-enabled fixture."""

import unittest

from tools.browser_fixture_mode import fixture_mode

READ = "frontend/e2e/read-poll-recovery.spec.ts"


class ReadObserverFixtureTests(unittest.TestCase):
    def test_single_observer_uses_read_only_fixture(self):
        self.assertEqual(fixture_mode({READ}), "read-only")

    def test_observer_and_existing_read_controls_stay_read_only(self):
        self.assertEqual(
            fixture_mode(
                {
                    READ,
                    "frontend/e2e/session-job-recovery.spec.ts",
                    "frontend/e2e/product-version.spec.ts",
                }
            ),
            "read-only",
        )

    def test_observer_preserves_an_explicit_controlled_sar_fixture(self):
        self.assertEqual(
            fixture_mode({READ, "frontend/e2e/sar-region-pointer.spec.ts"}), "sar"
        )

    def test_unknown_spec_does_not_receive_an_implicit_read_only_exemption(self):
        self.assertEqual(
            fixture_mode({"frontend/e2e/unregistered-control.spec.ts"}), "execution"
        )

    def test_isolated_api_recovery_ui_uses_no_execution_fixture(self):
        ui = "frontend/e2e/llm-recovery.spec.ts"
        for extra, expected in (
            (set(), "read-only"),
            ({READ}, "read-only"),
            ({"frontend/e2e/llm-recovery-stack.spec.ts"}, "llm-recovery"),
            ({"frontend/e2e/llm-settings.spec.ts"}, "llm-settings"),
            ({"frontend/e2e/real-workflow.spec.ts"}, "execution"),
            ({"frontend/e2e/unregistered-control.spec.ts"}, "execution"),
        ):
            with self.subTest(extra=extra):
                self.assertEqual(fixture_mode({ui, *extra}), expected)


if __name__ == "__main__":
    unittest.main()
