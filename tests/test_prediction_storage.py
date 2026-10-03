"""Real SQLite source/protocol binding and terminal prediction-state regressions."""

from __future__ import annotations

import json
import unittest

from test_prediction_support import PredictionFixture, controlled_summary
from test_web_support import ExitRunner

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import JobQueue
from patent_sar_extractor.web.prediction_storage import PredictionStore
from patent_sar_extractor.web.storage import now


class PredictionStorageTests(PredictionFixture, unittest.TestCase):
    def test_complete_persists_and_changed_smiles_or_source_are_stale(self):
        row, _, source = self.draft()
        self.service.predictions.put(
            self.project.id, "Compound 1", controlled_summary(source, "CCO", row["id"])
        )
        inputs = [("Compound 1", source, "CCO")]
        current = PredictionStore(self.service.store).summaries(
            self.project.id, inputs
        )["Compound 1"]
        self.assertEqual(current.status, "complete")
        self.assertEqual(len(current.properties), 6)
        for identity in (
            ("Compound 1", "0" * 64, "CCO"),
            ("Compound 1", source, "CCN"),
        ):
            self.assertEqual(
                self.service.predictions.summaries(self.project.id, [identity])[
                    "Compound 1"
                ].status,
                "stale",
            )

    def test_write_requires_current_source_effective_smiles_and_project_producer(self):
        row, _, source = self.draft()
        for summary in (
            controlled_summary("0" * 64, "CCO", row["id"]),
            controlled_summary(source, "CCN", row["id"]),
            controlled_summary(source, "CCO", "0" * 32),
        ):
            with (
                self.subTest(summary=summary.model_dump()),
                self.assertRaises(WebError),
            ):
                self.service.predictions.put(self.project.id, "Compound 1", summary)

    def test_terminal_producers_never_leave_running_or_pending_rows(self):
        row, _, source = self.draft()
        self.service.predictions.put(
            self.project.id,
            "Compound 1",
            controlled_summary(source, "CCO", row["id"], status="running"),
        )
        queue = JobQueue(self.service, ExitRunner(), 2)
        queue._finish(row["id"], "cancelled", None)
        current = self.service.predictions.summaries(
            self.project.id, [("Compound 1", source, "CCO")]
        )["Compound 1"]
        self.assertEqual(current.status, "failed")
        self.assertEqual(current.error.code, "admet_cancelled")
        with self.service.store.connect() as connection:
            saved = connection.execute(
                "SELECT payload FROM admet_predictions"
            ).fetchone()[0]
        self.assertNotIn('"status":"running"', saved)
        self.assertNotIn('"status":"pending"', saved)

    def test_corrupt_saved_engine_envelope_and_binding_fail_closed(self):
        row, _, source = self.draft()
        summary = controlled_summary(source, "CCO", row["id"])
        for mutation in ("engine", "schema", "compound", "source"):
            with self.subTest(mutation=mutation):
                self.service.predictions.put(self.project.id, "Compound 1", summary)
                with self.service.store.connect(write=True) as connection:
                    record = connection.execute(
                        "SELECT payload FROM admet_predictions"
                    ).fetchone()[0]
                    packet = json.loads(record)
                    observation = packet.get("observation", packet)
                    if mutation == "engine":
                        observation["engine"]["model_sha256"] = "0" * 64
                    elif mutation == "schema":
                        packet["schema"] = {"name": "unknown", "version": 999}
                    elif mutation == "compound":
                        packet["compound_id"] = "Compound 999"
                    else:
                        observation["source_fingerprint"] = "0" * 64
                    connection.execute(
                        "UPDATE admet_predictions SET payload=?,updated_at=?",
                        (json.dumps(packet), now()),
                    )
                current = self.service.predictions.summaries(
                    self.project.id, [("Compound 1", source, "CCO")]
                )["Compound 1"]
                self.assertEqual(current.status, "failed")
                self.assertEqual(current.properties, [])
