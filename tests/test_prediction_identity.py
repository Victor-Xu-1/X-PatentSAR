"""Canonical graph identity with real RDKit/SQLite and controlled model evidence."""

from __future__ import annotations

import hashlib
import json
import unittest
from contextlib import contextmanager
from functools import partial
from unittest.mock import Mock, patch

from test_prediction_support import PredictionFixture, controlled_summary

from patent_sar_extractor.web.admet_history import read_admet_stage
from patent_sar_extractor.web.analysis import AnalysisService
from patent_sar_extractor.web.analysis_chemistry import canonical_smiles, validate_batch
from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.prediction_jobs import correction_prediction
from patent_sar_extractor.web.prediction_storage import smiles_digest
from patent_sar_extractor.web.prediction_worker import run_predictions
from patent_sar_extractor.web.property_values import effective_property_values
from patent_sar_extractor.web.storage import now


class PredictionDigestTests(unittest.TestCase):
    def test_equivalent_graphs_share_the_canonical_analysis_input_digest(self):
        for left, right in (
            ("CCO", "OCC"),
            ("c1ccccc1", "C1=CC=CC=C1"),
            ("[Na+].CC(=O)[O-]", "CC(=O)[O-].[Na+]"),
            ("C[C@H](O)F", "O[C@@H](C)F"),
        ):
            with self.subTest(left=left, right=right):
                self.assertEqual(validate_batch([left]), validate_batch([right]))
                self.assertEqual(smiles_digest(left), smiles_digest(right))
                self.assertEqual(
                    smiles_digest(left),
                    hashlib.sha256(canonical_smiles(left).encode()).hexdigest(),
                )

    def test_stereo_isotope_charge_and_fragments_are_never_collapsed(self):
        for left, right in (
            ("C[C@H](O)F", "C[C@@H](O)F"),
            ("C/C=C/C", "C/C=C\\C"),
            ("CCO", "[13CH3]CO"),
            ("CN", "C[NH3+]"),
            ("CCO", "CCO.Cl"),
        ):
            with self.subTest(left=left, right=right):
                self.assertNotEqual(smiles_digest(left), smiles_digest(right))

    def test_invalid_queries_and_excessive_molecules_have_no_prediction_identity(self):
        for smiles in ("C(", "*CC", "[Xe]", "C" * 257, "CCO name", " " * 2049 + "CC"):
            with self.subTest(smiles=smiles[:20]), self.assertRaises(WebError):
                smiles_digest(smiles)


class PredictionIdentityStorageTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.service.corrections.on_save = partial(
            correction_prediction, self.service.store
        )

    def seed(self):
        job, _, source = self.draft()
        summary = controlled_summary(source, "CCO", job["id"])
        self.service.predictions.put(self.project.id, "Compound 1", summary)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete',finished_at=? WHERE id=?",
                (now(), job["id"]),
            )
        return source, summary

    def records(self):
        with self.service.store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM admet_predictions ORDER BY smiles_sha256"
                )
            ]

    def read(self, source, smiles):
        return self.service.predictions.summaries(
            self.project.id, [("Compound 1", source, smiles)]
        )["Compound 1"]

    def save(self, smiles, **addons):
        document = self.service.get_correction(self.project.id, "Compound 1")
        return self.service.put_correction(
            self.project.id,
            "Compound 1",
            CorrectionRequest.model_validate(
                {
                    "expected_revision": document.revision,
                    "expected_source_fingerprint": document.source_fingerprint,
                    "fields": {
                        **document.values.model_dump(),
                        "smiles": smiles,
                        **addons,
                    },
                }
            ),
        )

    def test_equivalent_save_preserves_prediction_provenance_and_manual_values(self):
        source, summary = self.seed()
        records = self.records()
        raw = self.service.store.compound(self.project.id, "Compound 1")
        jobs = self.service.job_ids(self.project.id)
        document = self.save(
            "OCC",
            property_overrides={"logP": 0, "tpsa": None},
            property_basis_smiles="OCC",
        )
        result = self.service.results(self.project.id).items[0]
        self.assertEqual(result.smiles, "OCC")
        self.assertEqual(result.admet.status, "complete")
        self.assertEqual(result.admet.model_dump(), summary.model_dump())
        self.assertEqual(effective_property_values(result)["logP"], 0)
        self.assertIsNone(effective_property_values(result)["tpsa"])
        self.assertEqual(document.source_fingerprint, source)
        self.assertEqual(
            self.service.store.compound(self.project.id, "Compound 1"), raw
        )
        self.assertEqual(self.service.job_ids(self.project.id), jobs)
        self.assertEqual(self.records(), records)

    def test_equivalent_graph_worker_reuses_verified_projection_without_model_work(
        self,
    ):
        source, original = self.seed()
        self.save("OCC")
        job, root, _ = self.draft()
        analysis = Mock(spec=AnalysisService)
        analysis.admet.side_effect = AssertionError("No inference for an identity hit")
        records = self.records()
        run_predictions(self.service, analysis, job)
        analysis.admet.assert_not_called()
        stage, _ = read_admet_stage(job, root)
        self.assertEqual(stage.status, "ok")
        self.assertEqual(stage.progress.cache_hits, 1)
        self.assertEqual((stage.progress.completed, stage.progress.total), (1, 1))
        self.assertEqual(self.read(source, "OCC").model_dump(), original.model_dump())
        self.assertEqual(self.records(), records)

    def test_actual_graph_change_invalidates_and_enqueues_only_target(self):
        source, _ = self.seed()
        before = self.records()
        self.save("CCN")
        current = self.read(source, "CCN")
        self.assertEqual(current.status, "stale")
        self.assertEqual(current.properties, [])
        self.assertEqual(self.records(), before)
        jobs = self.service.job_ids(self.project.id)
        self.assertEqual(len(jobs), 2)
        queued = next(
            self.service.store.job(job)
            for job in jobs
            if self.service.store.job(job)["status"] == "queued"
        )
        self.assertEqual(json.loads(queued["spec"])["admet_compounds"], ["Compound 1"])

    def test_alias_publication_uses_canonical_key_without_rewriting_saved_input(self):
        source, original = self.seed()
        self.save("NCC")
        job = next(
            self.service.store.job(job_id)
            for job_id in self.service.job_ids(self.project.id)
            if self.service.store.job(job_id)["status"] == "queued"
        )
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job["id"]),
            )
        observation = controlled_summary(source, "NCC", job["id"])
        self.service.predictions.put(self.project.id, "Compound 1", observation)
        self.assertEqual(
            self.read(source, "CCN").model_dump(), observation.model_dump()
        )
        self.assertEqual(
            self.service.effective_compound(self.project.id, "Compound 1").smiles, "NCC"
        )
        self.assertEqual(observation.smiles_sha256, hashlib.sha256(b"CCN").hexdigest())
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.read(source, "CCO").model_dump(), original.model_dump())

    def test_source_change_stays_stale_even_for_equivalent_graph(self):
        source, _ = self.seed()
        self.save("OCC")
        with self.service.store.connect(write=True) as connection:
            raw = self.service.store.compound(self.project.id, "Compound 1")
            payload = json.loads(raw["payload"])
            payload["display_id"] = "Changed raw source identity"
            connection.execute(
                "UPDATE compounds SET payload=? WHERE project_id=? AND id=?",
                (json.dumps(payload), self.project.id, "Compound 1"),
            )
        raw = self.service.store.compound(self.project.id, "Compound 1")
        current_source = correction_source_fingerprint(
            self.service.store.project(self.project.id), raw
        )
        self.assertNotEqual(current_source, source)
        self.assertEqual(self.read(current_source, "OCC").status, "stale")

    def legacy_record(self, summary):
        digest = hashlib.sha256(b"OCC").hexdigest()
        legacy = summary.model_copy(update={"smiles_sha256": digest})
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE admet_predictions SET smiles_sha256=?,payload=?",
                (
                    digest,
                    self.service.predictions._packet(
                        self.project.id, "Compound 1", legacy
                    ),
                ),
            )
        return legacy

    def test_legacy_exact_input_proof_is_readonly_and_unknown_aliases_stay_stale(self):
        source, summary = self.seed()
        self.save("OCC")
        legacy = self.legacy_record(summary)
        records = self.records()
        self.assertEqual(self.read(source, "OCC").model_dump(), legacy.model_dump())
        self.assertEqual(self.read(source, "CCO").status, "stale")
        self.assertEqual(self.read("0" * 64, "OCC").status, "stale")
        self.assertEqual(self.records(), records)

    def test_legacy_packet_digest_must_match_its_stored_key(self):
        source, summary = self.seed()
        self.save("OCC")
        self.legacy_record(summary)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE admet_predictions SET payload=?",
                (
                    self.service.predictions._packet(
                        self.project.id, "Compound 1", summary
                    ),
                ),
            )
        current = self.read(source, "OCC")
        self.assertEqual(current.status, "failed")
        self.assertEqual(current.properties, [])

    def test_canonical_record_wins_and_corruption_cannot_fall_back_to_legacy(self):
        source, summary = self.seed()
        self.save("OCC")
        self.legacy_record(summary)
        canonical = summary.model_copy(update={"warnings": ["canonical observation"]})
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO admet_predictions VALUES(?,?,?,?,?,?,?,?)",
                (
                    self.project.id,
                    "Compound 1",
                    source,
                    summary.smiles_sha256,
                    self.service.predictions.epoch,
                    self.service.predictions._packet(
                        self.project.id, "Compound 1", canonical
                    ),
                    now(),
                    summary.job_id,
                ),
            )
        self.assertEqual(self.read(source, "OCC").warnings, canonical.warnings)
        with self.service.store.connect(write=True) as connection:
            packet = json.loads(
                self.service.predictions._packet(
                    self.project.id, "Compound 1", canonical
                )
            )
            packet["observation"]["engine"]["model_sha256"] = "0" * 64
            connection.execute(
                "UPDATE admet_predictions SET payload=? WHERE smiles_sha256=?",
                (json.dumps(packet), summary.smiles_sha256),
            )
        self.assertEqual(self.read(source, "OCC").status, "failed")
        self.assertEqual(self.read(source, "OCC").properties, [])

    def test_only_current_epoch_runtime_and_pinned_engine_are_reused(self):
        source, summary = self.seed()
        original = json.loads(
            self.service.predictions._packet(self.project.id, "Compound 1", summary)
        )
        for mutation in ("engine", "runtime", "epoch"):
            with self.subTest(mutation=mutation):
                packet = json.loads(json.dumps(original))
                epoch = self.service.predictions.epoch
                if mutation == "engine":
                    packet["observation"]["engine"]["model_sha256"] = "0" * 64
                elif mutation == "runtime":
                    packet["runtime_identity"] = {}
                else:
                    epoch = "0" * 64
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE admet_predictions SET payload=?,epoch=?",
                        (json.dumps(packet), epoch),
                    )
                current = self.read(source, "OCC")
                self.assertEqual(
                    current.status, "stale" if mutation == "epoch" else "failed"
                )
                self.assertEqual(current.properties, [])

    def test_invalid_input_fails_individually_without_hiding_valid_prediction(self):
        source, _ = self.seed()
        result = self.service.predictions.summaries(
            self.project.id,
            [("invalid", source, "C("), ("Compound 1", source, "OCC")],
        )
        self.assertEqual(result["invalid"].status, "failed")
        self.assertEqual(result["invalid"].error.code, "admet_smiles_invalid")
        self.assertEqual(result["Compound 1"].status, "complete")

    def test_batch_reads_remain_bounded_without_per_row_audit_queries(self):
        source, _ = self.seed()
        statements = []
        connect = self.service.store.connect

        @contextmanager
        def trace(*args, **kwargs):
            with connect(*args, **kwargs) as connection:
                connection.set_trace_callback(statements.append)
                yield connection

        inputs = [(f"Compound {index}", source, "OCC") for index in range(1, 251)]
        with patch.object(self.service.store, "connect", trace):
            values = self.service.predictions.summaries(self.project.id, inputs)
        self.assertEqual(values["Compound 1"].status, "complete")
        self.assertEqual(len(values), 250)
        self.assertEqual(sum("WITH wanted" in sql for sql in statements), 3)
        self.assertFalse(any("correction_audit" in sql for sql in statements))


if __name__ == "__main__":
    unittest.main()
