"""Bounded, current, source-owned completion without rewriting scientific assets."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_corpus_predictions as corpus_tests
import test_existing_compound_completion as completion_tests
from test_prediction_support import PredictionFixture

from patent_sar_extractor.core.binding_catalog import compound_catalog
from patent_sar_extractor.web.acceptance import ARTIFACTS
from patent_sar_extractor.web.completion_inputs import completion_inputs
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.recognition_observations import (
    _saved_observation,
    checked_observation,
)
from patent_sar_extractor.web.recognition_sources import (
    recognition_sources,
    source_context,
)
from patent_sar_extractor.web.recognition_storage import RecognitionStore
from patent_sar_extractor.web.service import WorkspaceService
from tools.browser_fixture_mode import PREFIX, fixture_mode
from tools.prepare_browser_fixture import prepare


class CompletionObservationSafetyTests(PredictionFixture, unittest.TestCase):
    catalog = completion_tests.ExistingCompoundCompletionTests.catalog
    complete = completion_tests.ExistingCompoundCompletionTests.complete
    pending_reprints = completion_tests.ExistingCompoundCompletionTests.pending_reprints

    def test_browser_scope_only_uses_the_bounded_read_adapter(self):
        selected = {PREFIX + "source-completion.spec.ts"}
        self.assertEqual(fixture_mode(selected), "completion")
        self.assertEqual(
            fixture_mode(selected | {PREFIX + "topbar.spec.ts"}), "completion"
        )
        self.assertEqual(
            fixture_mode(selected | {PREFIX + "real-workflow.spec.ts"}), "execution"
        )

    def test_browser_adapter_retains_three_distinct_states_without_live_jobs(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "tools.prepare_browser_fixture.TestClient",
                side_effect=AssertionError("no CLI fixture"),
            ),
        ):
            values = prepare(Path(temporary) / "completion", completion=True)
            service = WorkspaceService(Path(values["PATENTSAR_WEB_STATE_DIR"]))
            for name, status in (
                ("PENDING", "unavailable"),
                ("COMPLETE", "valid"),
                ("CONFLICTING", "invalid"),
            ):
                project = values[f"PATENTSAR_E2E_COMPLETION_{name}_PROJECT"]
                first, second = service.results(project).items
                self.assertEqual(first.recognition.status, status)
                self.assertEqual(len(first.additional_sources), 1)
                if status == "valid":
                    self.assertEqual((first.smiles, second.smiles), ("CCO", "CCO"))
                else:
                    self.assertIsNone(first.smiles)
            with service.store.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
                    ).fetchone()[0],
                    0,
                )

    def test_fixture_cli_is_independent_of_callers_working_directory(self):
        repository = Path(__file__).resolve().parents[1]
        environment = {**os.environ, "PYTHONPATH": str(repository / "src")}
        with tempfile.TemporaryDirectory() as temporary:
            output = subprocess.check_output(
                [
                    sys.executable,
                    str(repository / "tools/prepare_browser_fixture.py"),
                    str(Path(temporary) / "state"),
                    "--completion",
                ],
                cwd=temporary,
                env=environment,
                text=True,
                timeout=30,
            )
        values = json.loads(output)
        self.assertEqual(values["PATENTSAR_E2E_RUN_JOBS"], "0")
        self.assertIn("PATENTSAR_E2E_COMPLETION_COMPLETE_PROJECT", values)

    def saved(self):
        row = self.pending_reprints()
        self.complete(row)
        with self.service.store.connect() as connection:
            saved = dict(
                connection.execute(
                    "SELECT * FROM compound_recognitions "
                    "WHERE project_id=? AND compound_id=?",
                    (self.project.id, "Compound 1"),
                ).fetchone()
            )
        return row, saved

    def test_corrupted_observation_or_runtime_cannot_break_other_rows_or_retain_graph(
        self,
    ):
        self.saved()
        with self.service.store.connect() as connection:
            baseline = dict(
                connection.execute(
                    "SELECT * FROM compound_recognitions "
                    "WHERE project_id=? AND compound_id=?",
                    (self.project.id, "Compound 1"),
                ).fetchone()
            )
        malformed = {**json.loads(baseline["observation"]), "reprint_records": None}
        for column in ("observation", "runtime_identity"):
            for corrupt in ("{", "[]", "null", json.dumps(malformed)):
                with self.subTest(column=column, corrupt=corrupt):
                    with self.service.store.connect(write=True) as connection:
                        connection.execute(
                            "UPDATE compound_recognitions SET observation=?,runtime_identity=? "
                            "WHERE project_id=? AND compound_id=?",
                            (
                                corrupt
                                if column == "observation"
                                else baseline["observation"],
                                corrupt
                                if column == "runtime_identity"
                                else baseline["runtime_identity"],
                                self.project.id,
                                "Compound 1",
                            ),
                        )
                    self.service = WorkspaceService(self.state)
                    first, other = self.service.results(self.project.id).items
                    self.assertEqual(first.recognition.status, "unavailable")
                    self.assertIsNone(first.smiles)
                    self.assertEqual(first.admet.properties, [])
                    self.assertEqual(
                        (other.recognition.status, other.smiles), ("valid", "CCO")
                    )

    def test_removed_printed_owner_cannot_reuse_a_saved_graph_without_refresh(self):
        self.saved()
        path = self.run / ARTIFACTS["bindings"][0]
        payload = json.loads(path.read_text())
        payload["compound_catalog"] = compound_catalog(
            payload["compound_catalog"]["entries"][1:], []
        )
        payload["final_bindings"] = []
        path.write_text(json.dumps(payload))
        binding, _ = recognition_sources(
            self.service.store.project(self.project.id), "Compound 1"
        )
        self.assertIsNone(binding)
        first = self.service.results(self.project.id).items[0]
        self.assertIsNone(first.smiles)
        self.assertEqual(first.recognition.status, "unavailable")
        self.assertEqual(first.admet.properties, [])

    def test_removed_single_original_owner_cannot_reuse_or_publish_a_saved_graph(self):
        row, _ = self.saved()
        with self.service.store.connect() as connection:
            saved = dict(
                connection.execute(
                    "SELECT * FROM compound_recognitions WHERE project_id=? AND compound_id=?",
                    (self.project.id, "Compound 8"),
                ).fetchone()
            )
        path = self.run / ARTIFACTS["bindings"][0]
        payload = json.loads(path.read_text())
        first = payload["compound_catalog"]["entries"][0]
        payload["compound_catalog"] = compound_catalog(
            [first], first["additional_sources"]
        )
        path.write_text(json.dumps(payload))
        binding, _ = recognition_sources(
            self.service.store.project(self.project.id), "Compound 8"
        )
        self.assertIsNone(binding)
        single = self.service.results(self.project.id).items[1]
        self.assertIsNone(single.smiles)
        self.assertEqual(single.recognition.status, "unavailable")
        with self.assertRaises(WebError) as rejected:
            RecognitionStore(self.service.store).put(
                self.project.id,
                "Compound 8",
                source=saved["source_fingerprint"],
                crop=saved["crop_sha256"],
                record=json.loads(saved["observation"]),
                job_id=row["id"],
            )
        self.assertEqual(rejected.exception.code, "recognition_source_changed")

    def test_changed_additional_crop_only_invalidates_its_completed_owner(self):
        row = self.pending_reprints()
        path = self.run / ARTIFACTS["bindings"][0]
        payload = json.loads(path.read_text())
        source = payload["compound_catalog"]["entries"][0]["additional_sources"][0]
        separate = self.run / "independent-original.png"
        shutil.copyfile(source["image_path"], separate)
        source["image_path"] = str(separate)
        path.write_text(json.dumps(payload))
        path = self.run / ARTIFACTS["structures"][0]
        metadata = json.loads(path.read_text())
        for item in metadata["structures"]:
            if item["structure_id"] == source["structure_id"]:
                item["image_path"] = str(separate)
        path.write_text(json.dumps(metadata))
        self.service.refresh(self.project.id)
        self.complete(row)
        self.assertTrue(
            all(item.smiles for item in self.service.results(self.project.id).items)
        )
        separate.write_bytes(separate.read_bytes() + b"modified original")
        first, other = self.service.results(self.project.id).items
        self.assertEqual(first.recognition.status, "unavailable")
        self.assertIsNone(first.smiles)
        self.assertEqual(first.admet.properties, [])
        self.assertEqual((other.recognition.status, other.smiles), ("valid", "CCO"))

    def test_cancelled_producer_is_refused_before_source_io(self):
        row, saved = self.saved()
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET cancel_requested=1 WHERE id=?", (row["id"],)
            )
        with (
            patch(
                "patent_sar_extractor.web.recognition_storage.recognition_sources",
                side_effect=AssertionError(
                    "cancelled producer must not read source assets"
                ),
            ),
            self.assertRaises(WebError) as cancelled,
        ):
            RecognitionStore(self.service.store).put(
                self.project.id,
                "Compound 1",
                source=saved["source_fingerprint"],
                crop=saved["crop_sha256"],
                record=json.loads(saved["observation"]),
                job_id=row["id"],
            )
        self.assertEqual(cancelled.exception.code, "recognition_cancelled")

    def test_source_budget_counts_aliases_before_observation_work(self):
        self.pending_reprints()
        project = self.service.store.project(self.project.id)
        rows = {row["id"]: row for row in self.service.result_rows(self.project.id)}
        compounds = self.service.result_queries.effective_compounds(self.project.id)
        with (
            patch(
                "patent_sar_extractor.web.completion_inputs.MAX_RECOGNITION_SOURCES", 1
            ),
            patch(
                "patent_sar_extractor.web.completion_inputs.crop_digest",
                side_effect=AssertionError("over-budget source must not be observed"),
            ),
            self.assertRaises(WebError) as rejected,
        ):
            completion_inputs(project, rows, compounds)
        self.assertEqual(
            (rejected.exception.status, rejected.exception.code),
            (413, "recognition_source_limit"),
        )

    def test_invalid_producer_selection_is_refused_before_source_reads(self):
        row, saved = self.saved()
        for selection in (12, "Compound 1", [None], None):
            with self.subTest(selection=selection):
                spec = {**json.loads(row["spec"]), "admet_compounds": selection}
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE jobs SET spec=? WHERE id=?",
                        (json.dumps(spec), row["id"]),
                    )
                with (
                    patch(
                        "patent_sar_extractor.web.recognition_storage.recognition_sources",
                        side_effect=AssertionError(
                            "invalid producer must not read source assets"
                        ),
                    ),
                    self.assertRaises(WebError) as rejected,
                ):
                    RecognitionStore(self.service.store).put(
                        self.project.id,
                        "Compound 1",
                        source=saved["source_fingerprint"],
                        crop=saved["crop_sha256"],
                        record=json.loads(saved["observation"]),
                        job_id=row["id"],
                    )
                self.assertEqual(rejected.exception.code, "recognition_cancelled")

    def test_oversized_packet_and_context_are_refused_before_parsing_or_source_reads(
        self,
    ):
        with (
            patch(
                "patent_sar_extractor.web.recognition_observations.MAX_COMPLETION_BYTES",
                16,
            ),
            patch(
                "patent_sar_extractor.web.recognition_observations.json.loads",
                side_effect=AssertionError("oversized data must not be parsed"),
            ),
        ):
            for content, context in (("x" * 17, "{}"), ("{}", "x" * 17)):
                with self.assertRaises(WebError) as rejected:
                    _saved_observation(content, "Compound 1", "S0", context)
                self.assertEqual(rejected.exception.code, "invalid_recognition")
            with self.assertRaises(WebError):
                checked_observation({"raw_smiles": "C" * 20}, "Compound 1", "S0")
        with (
            patch(
                "patent_sar_extractor.web.recognition_sources.MAX_COMPLETION_BYTES", 16
            ),
            self.assertRaises(WebError) as rejected,
        ):
            source_context({"cpd": "Compound 1"}, str(self.run))
        self.assertEqual(rejected.exception.code, "recognition_source_limit")

    def test_current_observed_disagreement_is_not_resampled_by_a_later_job(self):
        row = self.pending_reprints()
        completion_tests.ControlledConverter.raw_by_source = {"proved-reprint": "CCC"}
        self.complete(row)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete' WHERE id=?", (row["id"],)
            )
        later = corpus_tests.CorpusPredictionTests.job(self)[0]
        calls = list(completion_tests.ControlledConverter.source_calls)
        self.complete(later)
        self.assertEqual(completion_tests.ControlledConverter.source_calls, calls)
        first = self.service.results(self.project.id).items[0]
        self.assertEqual(first.recognition.status, "invalid")
        self.assertIsNone(first.smiles)


if __name__ == "__main__":
    unittest.main()
