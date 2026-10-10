"""Only independent-SAR CI fixture selection and no-extraction preparation."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from test_web_support import ARTIFACTS, WebFixture, artifact_run, make_pdf

from tools.browser_fixture_mode import PREFIX, fixture_mode
from tools.prepare_browser_fixture import prepare


class SARBrowserFixtureTests(WebFixture, unittest.TestCase):
    def test_card_inspection_scope_uses_only_isolated_protocol_and_source(self):
        selected = {
            PREFIX + "sar-card-inspection.spec.ts",
            PREFIX + "product-version.spec.ts",
        }
        self.assertEqual(fixture_mode(selected), "sar")
        members = {
            PREFIX + "sar-member-navigation.spec.ts",
            PREFIX + "product-version.spec.ts",
        }
        self.assertEqual(fixture_mode(members), "sar")
        sources = {
            PREFIX + "sar-candidate-source.spec.ts",
            PREFIX + "product-version.spec.ts",
        }
        self.assertEqual(fixture_mode(sources), "sar")
        self.assertEqual(
            fixture_mode(sources | {PREFIX + "real-workflow.spec.ts"}), "execution"
        )
        self.assertEqual(
            fixture_mode(members | {PREFIX + "sar-card-inspection.spec.ts"}), "sar"
        )
        self.assertEqual(
            fixture_mode(members | {PREFIX + "real-workflow.spec.ts"}), "execution"
        )
        self.assertEqual(
            fixture_mode(selected | {PREFIX + "real-workflow.spec.ts"}), "execution"
        )

    def test_atom_label_samples_preserve_default_adapter_graphs_without_jobs(self):
        browser = self.root / "browser"
        with patch(
            "tools.prepare_browser_fixture.TestClient",
            side_effect=AssertionError("No execution fixture allowed"),
        ):
            values = prepare(browser, sar=True)
        self.assertEqual(values["PATENTSAR_E2E_RUN_JOBS"], "0")
        records = json.loads(
            (browser / "controlled-history" / ARTIFACTS["smiles"][0]).read_text()
        )["records"]
        by_label = {row["cpd_id"]: row for row in records}
        self.assertEqual(len(records), 30)
        for label, count in (("Compound 29", 16), ("Compound 30", 116)):
            row = by_label[label]
            self.assertEqual(row["smiles"], "C" * count)
            self.assertEqual(row["raw_smiles"], row["smiles"])
            self.assertEqual(row["heavy_atom_count"], count)
            self.assertTrue(row["rdkit_valid"])
        self.assertTrue(
            all(
                row["smiles"] == "CCO"
                for label, row in by_label.items()
                if label not in {"Compound 29", "Compound 30"}
            )
        )
        pdf = make_pdf(self.root / "default.pdf")
        default = artifact_run(self.root / "default", pdf)
        self.assertTrue(
            all(
                row["smiles"] == "CCO"
                for row in json.loads((default / ARTIFACTS["smiles"][0]).read_text())[
                    "records"
                ]
            )
        )

    def test_atom_label_scope_never_selects_execution_fixture(self):
        selected = {
            PREFIX + "sar-atom-label.spec.ts",
            PREFIX + "sar-selection-viewport.spec.ts",
            PREFIX + "product-version.spec.ts",
        }
        self.assertEqual(fixture_mode(selected), "sar")
        self.assertEqual(fixture_mode({PREFIX + "sar-atom-label.spec.ts"}), "sar")
        self.assertEqual(
            fixture_mode(selected | {PREFIX + "real-workflow.spec.ts"}), "execution"
        )

    def test_region_recovery_scope_uses_only_isolated_snapshot_and_region_writes(self):
        selected = {
            PREFIX + "sar-region-recovery.spec.ts",
            PREFIX + "sar-selection-viewport.spec.ts",
            PREFIX + "product-version.spec.ts",
        }
        self.assertEqual(fixture_mode(selected), "sar")
        self.assertEqual(
            fixture_mode(selected | {PREFIX + "real-workflow.spec.ts"}), "execution"
        )

    def test_selection_viewport_scope_uses_snapshot_only_synthetic_source(self):
        selected = {
            PREFIX + "sar-selection-viewport.spec.ts",
            PREFIX + "product-version.spec.ts",
        }
        self.assertEqual(fixture_mode(selected), "sar")
        self.assertEqual(
            fixture_mode(selected | {PREFIX + "real-workflow.spec.ts"}), "execution"
        )

    def test_filter_viewport_scope_uses_only_read_only_source(self):
        selected = {
            PREFIX + "column-filter-viewport.spec.ts",
            PREFIX + "product-version.spec.ts",
        }
        self.assertEqual(fixture_mode(selected), "read-only")
        self.assertEqual(
            fixture_mode(selected | {PREFIX + "real-workflow.spec.ts"}),
            "execution",
        )

    def test_structure_detail_scope_uses_only_read_only_imported_source(self):
        self.assertEqual(
            fixture_mode(
                {
                    PREFIX + "structure-details.spec.ts",
                    PREFIX + "expert-controls.spec.ts",
                    PREFIX + "product-version.spec.ts",
                }
            ),
            "read-only",
        )

    def test_editor_viewport_scope_uses_only_imported_read_only_source(self):
        self.assertEqual(
            fixture_mode(
                {PREFIX + "editor-viewport.spec.ts", PREFIX + "product-version.spec.ts"}
            ),
            "read-only",
        )

    def test_density_scope_adds_only_read_only_recent_file_checks(self):
        recent = PREFIX + "recent-density.spec.ts"
        self.assertEqual(fixture_mode({recent}), "read-only")
        self.assertEqual(
            fixture_mode(
                {
                    recent,
                    PREFIX + "sar-study.spec.ts",
                    PREFIX + "product-version.spec.ts",
                }
            ),
            "sar",
        )

    def test_ui_recovery_scope_uses_imported_synthetic_source_without_extraction(self):
        self.assertEqual(
            fixture_mode(
                {
                    PREFIX + "correction-response.spec.ts",
                    PREFIX + "expert-controls.spec.ts",
                    PREFIX + "expert-visual.spec.ts",
                    PREFIX + "product-version.spec.ts",
                }
            ),
            "sar",
        )
        self.assertEqual(
            fixture_mode(
                {PREFIX + "expert-visual.spec.ts", PREFIX + "expert-controls.spec.ts"}
            ),
            "read-only",
        )

    def test_selected_scope_chooses_sar_without_changing_other_fixture_modes(self):
        self.assertEqual(fixture_mode({PREFIX + "sar-workbench.spec.ts"}), "sar")
        self.assertEqual(fixture_mode({PREFIX + "sar-study.spec.ts"}), "sar")
        self.assertEqual(
            fixture_mode(
                {
                    PREFIX + "sar-study.spec.ts",
                    PREFIX + "expert-visual.spec.ts",
                    PREFIX + "expert-controls.spec.ts",
                    PREFIX + "product-version.spec.ts",
                }
            ),
            "sar",
        )
        self.assertEqual(
            fixture_mode(
                {PREFIX + "sar-workbench.spec.ts", PREFIX + "sar-study.spec.ts"}
            ),
            "sar",
        )
        self.assertEqual(fixture_mode({PREFIX + "topbar.spec.ts"}), "read-only")
        self.assertEqual(
            fixture_mode({PREFIX + "llm-settings.spec.ts"}), "llm-settings"
        )
        self.assertEqual(
            fixture_mode({PREFIX + "llm-recovery-stack.spec.ts"}), "llm-recovery"
        )
        self.assertEqual(
            fixture_mode(
                {PREFIX + "sar-workbench.spec.ts", PREFIX + "real-workflow.spec.ts"}
            ),
            "execution",
        )

    def test_sar_fixture_creates_adapter_source_but_never_runs_extraction(self):
        with patch(
            "tools.prepare_browser_fixture.TestClient",
            side_effect=AssertionError("No extraction fixture allowed"),
        ):
            values = prepare(self.root / "browser", sar=True)
        self.assertEqual(values["PATENTSAR_E2E_RUN_JOBS"], "0")
        self.assertEqual(
            values["PATENTSAR_E2E_SAR_MUTATIONS"], "synthetic-isolated-state"
        )
        receipt = json.loads((self.root / "browser/browser-fixture.json").read_text())
        self.assertTrue(receipt["sar_synthetic_scope"])
        self.assertFalse(receipt["scientific_acceptance_evidence"])
        self.assertFalse(receipt["real_cli_failure"])
        with self.assertRaises(ValueError):
            prepare(self.root / "unused", sar=True, read_only=True)


if __name__ == "__main__":
    unittest.main()
