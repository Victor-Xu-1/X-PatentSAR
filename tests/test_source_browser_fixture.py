"""Source browser checks use honest controlled molecular preconditions."""

import unittest

from tools.browser_fixture_mode import fixture_mode


class SourceBrowserFixtureTests(unittest.TestCase):
    def test_record_counts_need_only_the_existing_read_only_source_adapter(self):
        selected = {"frontend/e2e/record-count.spec.ts"}
        self.assertEqual(fixture_mode(selected), "read-only")
        self.assertEqual(
            fixture_mode(selected | {"frontend/e2e/source-completion.spec.ts"}),
            "completion",
        )

    def test_structure_reading_uses_existing_current_completion_adapters(self):
        selected = {"frontend/e2e/structure-details.spec.ts"}
        self.assertEqual(fixture_mode(selected), "completion")
        self.assertEqual(
            fixture_mode(selected | {"frontend/e2e/product-version.spec.ts"}),
            "completion",
        )

    def test_unrelated_read_only_or_feature_scopes_retain_their_own_preconditions(self):
        self.assertEqual(
            fixture_mode({"frontend/e2e/product-version.spec.ts"}), "read-only"
        )
        self.assertEqual(
            fixture_mode(
                {
                    "frontend/e2e/sar-workbench.spec.ts",
                    "frontend/e2e/structure-details.spec.ts",
                }
            ),
            "sar",
        )
        self.assertEqual(
            fixture_mode(
                {
                    "frontend/e2e/source-completion.spec.ts",
                    "frontend/e2e/structure-details.spec.ts",
                }
            ),
            "completion",
        )


if __name__ == "__main__":
    unittest.main()
