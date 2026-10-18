"""Source browser checks use honest controlled molecular preconditions."""

import json
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.artifact_catalog import MARKER
from patent_sar_extractor.artifact_io import load_json
from tools.browser_fixture_mode import fixture_mode


class SourceBrowserFixtureTests(unittest.TestCase):
    def test_candidate_observation_scope_never_selects_unrelated_execution(self):
        selected = {"frontend/e2e/candidate-observations.spec.ts"}
        self.assertEqual(fixture_mode(selected), "candidate-observations")
        self.assertEqual(
            fixture_mode(selected | {"frontend/e2e/product-version.spec.ts"}),
            "candidate-observations",
        )

    def test_native_candidate_fixture_stays_persistent_read_only_and_unaccepted(self):
        from patent_sar_extractor.web.service import WorkspaceService
        from tools.prepare_browser_fixture import prepare

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "isolated"
            values = prepare(root, candidate_observations=True)
            self.assertEqual(values["PATENTSAR_E2E_RUN_JOBS"], "0")
            proof = json.loads((root / "browser-fixture.json").read_text())
            self.assertFalse(proof["real_model_execution"])
            self.assertFalse(proof["scientific_acceptance_evidence"])
            service = WorkspaceService(Path(values["PATENTSAR_WEB_STATE_DIR"]))
            project = service.project(values["PATENTSAR_E2E_CANDIDATE_PROJECT_ID"])
            self.assertEqual(project.acceptance.state, "failed")
            rows = service.results(project.id).items
            self.assertEqual(len(rows), 2)
            self.assertTrue(
                all(row.smiles is None and not row.activities for row in rows)
            )
            self.assertTrue(
                all(
                    row.recognition.quality_flag == "unassigned_source_identity"
                    for row in rows
                )
            )
            with service.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )

    def test_shared_artifact_scope_uses_only_lossless_read_only_adapter_transport(self):
        from tools.prepare_browser_fixture import prepare

        self.assertEqual(
            fixture_mode({"frontend/e2e/binding-artifact.spec.ts"}), "read-only"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "isolated"
            values = prepare(root, read_only=True)
            path = root / "controlled-history/structure_bindings/bindings.json"
            self.assertIn(MARKER, json.loads(path.read_text()))
            self.assertEqual(len(load_json(path, {})["final_bindings"]), 30)
            self.assertEqual(values["PATENTSAR_E2E_RUN_JOBS"], "0")
            self.assertEqual(values["PATENTSAR_E2E_BINDING_TRANSPORT"], "shared-json-1")

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
