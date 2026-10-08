"""Release labels are provenance; controlled records never certify model accuracy."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_job_attempts as attempt_cases
from test_prediction_support import (
    PredictionFixture,
    controlled_stage,
    controlled_summary,
)
from test_web_support import WebFixture

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.stage_cache import (
    _fingerprint_matches,
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.admet_history import (
    read_admet_stage,
    seal_admet_stage,
    write_admet_stage,
)
from patent_sar_extractor.web.attempts import ARTIFACTS
from patent_sar_extractor.web.correction_models import CorrectionRequest, EditableFields
from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.descriptor_fields import (
    compute_descriptors,
    descriptor_engine,
)
from patent_sar_extractor.web.descriptor_models import DescriptorSummary
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import decode_spec
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.prediction_identity import compound_prediction_eligible
from patent_sar_extractor.web.processes import (
    runtime_identity,
    runtime_identity_matches,
)
from patent_sar_extractor.web.property_values import effective_property_values
from patent_sar_extractor.web.recognition_storage import RecognitionStore, crop_digest
from patent_sar_extractor.web.storage import encode, now

OLD_RELEASE = "0.1.0"


def incompatible_identities():
    """Negative fixture data, not a second compatibility predicate."""
    original = runtime_identity()
    for field, value in (
        ("product", {"name": "Foreign", "version": OLD_RELEASE}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.1.100"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "00.1.0"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.01.0"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.10.0"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "0.1.01"}),
        ("product", {"name": core.PRODUCT_NAME, "version": "v0.1.0"}),
        ("product", {**core.product_ref(), "unreviewed": True}),
        ("product", {"name": core.PRODUCT_NAME, "version": True}),
        ("pipeline_contract", {"name": "foreign", "version": "3.0.0"}),
        ("pipeline_contract", {**core.pipeline_contract_ref(), "version": "2.0.0"}),
        ("ruleset", {**core.ruleset_ref(), "version": "2.0.0"}),
    ):
        yield field, {**copy.deepcopy(original), field: value}
    yield "missing", {"product": core.product_ref()}
    yield "extra", {**original, "unreviewed": True}
    yield "null", None


class ReleaseIdentityTests(unittest.TestCase):
    def test_runtime_helper_is_canonical_complete_and_nonmutating(self):
        expected = runtime_identity()
        for label in (OLD_RELEASE, "0.1.1", "0.1.99", "0.2.0", "1.0.0"):
            actual = copy.deepcopy(expected)
            actual["product"]["version"] = label
            before = copy.deepcopy(actual)
            with self.subTest(label=label):
                self.assertTrue(runtime_identity_matches(actual))
                self.assertEqual(actual, before)
        for reason, actual in incompatible_identities():
            with self.subTest(reason=reason):
                before = copy.deepcopy(actual)
                self.assertFalse(runtime_identity_matches(actual))
                self.assertEqual(actual, before)
        with patch.object(
            core, "release_compatible_record", return_value=False
        ) as match:
            self.assertFalse(runtime_identity_matches(expected))
            match.assert_called_once_with(expected, runtime_identity())


class ReleaseCacheTests(WebFixture, unittest.TestCase):
    def test_old_manifest_label_reuses_only_an_identical_complete_fingerprint(self):
        output = self.root / "stage.json"
        output.write_bytes(b"immutable controlled stage")
        with patch.object(core, "__version__", OLD_RELEASE):
            fingerprint = _step_fingerprint("activity", pdf_path=str(self.pdf))
            _write_step_manifest(str(output), fingerprint)
        path = Path(str(output) + ".manifest.json")
        saved = path.read_bytes()
        expected = _step_fingerprint("activity", pdf_path=str(self.pdf))
        self.assertTrue(_fingerprint_matches(str(output), expected))
        self.assertEqual(path.read_bytes(), saved)
        for field, value in (
            ("product", {"name": core.PRODUCT_NAME, "version": "0.1.100"}),
            ("pipeline_contract", {**core.pipeline_contract_ref(), "version": "2.0.0"}),
            ("ruleset", {**core.ruleset_ref(), "version": "2.0.0"}),
            ("pdf_sha256", "0" * 64),
            ("dependency_sha256", {"foreign": "0" * 64}),
            ("params_digest", "0" * 64),
            ("params", {"stereo_evidence_version": 0}),
        ):
            packet = json.loads(saved)
            packet["fingerprint"][field] = value
            write_json_atomic(path, packet)
            with self.subTest(field=field):
                self.assertFalse(_fingerprint_matches(str(output), expected))
        for change in ("missing", "extra"):
            packet = json.loads(saved)
            if change == "missing":
                del packet["fingerprint"]["params"]
            else:
                packet["fingerprint"]["unreviewed"] = True
            write_json_atomic(path, packet)
            with self.subTest(change=change):
                self.assertFalse(_fingerprint_matches(str(output), expected))
        path.write_bytes(saved)
        self.pdf.write_bytes(self.pdf.read_bytes() + b"\nchanged original bytes")
        self.assertFalse(
            _fingerprint_matches(
                str(output), _step_fingerprint("activity", pdf_path=str(self.pdf))
            )
        )
        self.assertEqual(path.read_bytes(), saved)


class ReleaseQueueTests(WebFixture, unittest.TestCase):
    def draft_old(self):
        with patch.object(core, "__version__", OLD_RELEASE):
            return attempt_cases.AttemptTests.draft(self)

    def test_old_queued_job_decodes_and_keeps_source_led_pending_order(self):
        service, _, queue, job, spec = self.draft_old()
        before = service.store.job(job.id)
        self.assertEqual(queue._spec(job.id), spec)
        self.assertEqual(decode_spec(before["spec"]), spec)
        history = service.attempts.observe(before)
        self.assertEqual(
            [stage.name for stage in history.stages], list(core.CORE_STAGE_ORDER)
        )
        self.assertEqual(history.stage_order, list(core.CORE_STAGE_ORDER))
        self.assertEqual(service.store.job(job.id), before)

    def test_old_stopped_job_resumes_with_checkpoint_and_provenance_unchanged(self):
        with patch.object(core, "__version__", OLD_RELEASE):
            service, project, queue, job, spec = attempt_cases.AttemptTests.draft(self)
            attempt_cases.AttemptTests.classification(self, spec)
            attempt_cases.AttemptTests.summary(self, spec)
            attempt_cases.AttemptTests.finish(self, service, queue, job)
        root = Path(spec.output_dir)
        source = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        previous = service.store.job(job.id)
        history = self.state / "job-history" / f"{job.id}.json"
        sealed = history.read_bytes()
        self.assertTrue(service.job(job.id).can_resume)
        resumed = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        target = Path(queue._spec(resumed.id).output_dir)
        artifact = target / ARTIFACTS["classify"][0]
        self.assertTrue(artifact.is_file())
        self.assertEqual(
            json.loads(artifact.read_bytes())["product"]["version"], OLD_RELEASE
        )
        manifest = json.loads(Path(str(artifact) + ".manifest.json").read_bytes())
        self.assertEqual(manifest["fingerprint"]["product"]["version"], OLD_RELEASE)
        self.assertTrue(
            _fingerprint_matches(
                str(artifact),
                _step_fingerprint(
                    "classify",
                    pdf_path=spec.pdf_path,
                    params={"patent_id": spec.patent_id},
                ),
            )
        )
        self.assertFalse((target / "pipeline_summary.json").exists())
        self.assertFalse((target / "final_qa_report.json").exists())
        self.assertEqual(service.store.job(job.id), previous)
        self.assertEqual(history.read_bytes(), sealed)
        self.assertEqual({path: path.read_bytes() for path in source}, source)
        self.assertIsNone(queue.thread)
        self.assertEqual(queue.runner._children, {})

    def test_queue_rejects_scientific_foreign_invalid_and_source_mismatch(self):
        service, project, queue, job, _ = self.draft_old()
        original = service.store.job(job.id)
        for reason, identity in incompatible_identities():
            payload = json.loads(original["spec"])
            payload["runtime_identity"] = identity
            with self.subTest(reason=reason), self.assertRaises(WebError) as error:
                decode_spec(encode(payload))
            self.assertEqual(error.exception.code, "resume_identity")
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET sha256=? WHERE id=?", ("0" * 64, project.id)
            )
        with self.assertRaises(WebError) as error:
            queue._spec(job.id)
        self.assertEqual(error.exception.code, "unsafe_job_workspace")
        self.assertEqual(service.store.job(job.id), original)


class ReleaseObservationTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        with patch.object(core, "__version__", OLD_RELEASE):
            super().setUp()
        self.recognitions = RecognitionStore(self.service.store)

    def seed_old(self, *, terminal=True):
        with patch.object(core, "__version__", OLD_RELEASE):
            row, root, source = self.draft()
            prediction = controlled_summary(source, "CCO", row["id"])
            descriptors = DescriptorSummary(
                status="complete",
                properties=compute_descriptors("CCO"),
                engine=descriptor_engine(),
                source_fingerprint=source,
                smiles_sha256=prediction.smiles_sha256,
                job_id=row["id"],
                generated_at=now(),
            )
            record = json.loads((self.run / "smiles/smiles_results.json").read_bytes())[
                "records"
            ][0]
            record["model_fingerprint"] = "a" * 64
            raw = self.service.store.compound(self.project.id, "Compound 1")
            crop = crop_digest(self.run, raw["image_path"])
            self.recognitions.put(
                self.project.id,
                "Compound 1",
                source=source,
                crop=crop,
                record=record,
                job_id=row["id"],
            )
            self.service.predictions.put(self.project.id, "Compound 1", prediction)
            self.service.descriptors.put(self.project.id, "Compound 1", descriptors)
            write_admet_stage(root, row, controlled_stage(), core_completed=False)
            if terminal:
                stamp = now()
                seal_admet_stage(self.state, root, row, "complete", stamp)
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE jobs SET status='complete',finished_at=? WHERE id=?",
                        (stamp, row["id"]),
                    )
        return (
            self.service.store.job(row["id"]),
            root,
            source,
            prediction,
            descriptors,
            record,
            crop,
        )

    def saved_rows(self):
        with self.service.store.connect() as connection:
            return {
                table: [
                    tuple(row) for row in connection.execute(f"SELECT * FROM {table}")
                ]
                for table in (
                    "projects",
                    "compounds",
                    "jobs",
                    "admet_predictions",
                    "molecular_descriptors",
                    "compound_recognitions",
                    "corrections",
                    "correction_audit",
                )
            }

    def test_label_only_reads_preserve_projection_properties_recognition_and_history(
        self,
    ):
        row, root, source, prediction, descriptors, _, _ = self.seed_old()
        before = self.saved_rows()
        files = {
            path: path.read_bytes()
            for path in (
                self.pdf,
                root / "admet-stage.json",
                self.state / "job-history" / f"{row['id']}-admet.json",
                *(path for path in self.run.rglob("*") if path.is_file()),
            )
        }
        with patch.object(
            self.service,
            "refresh",
            side_effect=AssertionError("No label-only projection rebuild"),
        ):
            self.service.project(self.project.id)
            item = self.service.effective_compound(self.project.id, "Compound 1")
        self.assertEqual(item.recognition.status, "valid")
        inputs = [("Compound 1", source, "CCO")]
        self.assertEqual(
            self.service.predictions.summaries(self.project.id, inputs)["Compound 1"],
            prediction,
        )
        self.assertEqual(
            self.service.descriptors.summaries(self.project.id, inputs)["Compound 1"],
            descriptors,
        )
        stage, core_completed = read_admet_stage(row, root, state_root=self.state)
        self.assertEqual(stage, controlled_stage())
        self.assertFalse(core_completed)
        self.assertEqual(self.saved_rows(), before)
        self.assertEqual({path: path.read_bytes() for path in files}, files)

    def test_label_only_upgrade_preserves_manual_source_hash_values_and_audit(self):
        _, _, source, prediction, descriptors, _, _ = self.seed_old()
        with patch.object(core, "__version__", OLD_RELEASE):
            document = self.service.get_correction(self.project.id, "Compound 1")
            self.service.put_correction(
                self.project.id,
                "Compound 1",
                CorrectionRequest(
                    expected_revision=document.revision,
                    expected_source_fingerprint=document.source_fingerprint,
                    fields=EditableFields(
                        **{
                            **document.values.model_dump(),
                            "display_id": "Reviewed original identifier",
                            "property_overrides": {"logP": 0, "tpsa": None},
                            "property_basis_smiles": "CCO",
                        }
                    ),
                ),
            )
        before = self.saved_rows()
        original = self.service.store.project(self.project.id)
        raw = self.service.store.compound(self.project.id, "Compound 1")
        self.assertEqual(correction_source_fingerprint(original, raw), source)
        with patch.object(
            self.service,
            "refresh",
            side_effect=AssertionError(
                "Release changes must not replace producer identity"
            ),
        ):
            item = self.service.compounds(self.project.id)[0]
        self.assertFalse(item.correction.stale)
        self.assertEqual(item.display_id, "Reviewed original identifier")
        self.assertEqual(item.admet, prediction)
        self.assertEqual(item.descriptors, descriptors)
        values = effective_property_values(item)
        self.assertEqual(values["logP"], 0)
        self.assertIsNone(values["tpsa"])
        after = self.service.store.project(self.project.id)
        self.assertEqual(correction_source_fingerprint(after, raw), source)
        self.assertEqual(after["snapshot"], original["snapshot"])
        self.assertEqual(self.saved_rows(), before)

    def test_recognition_and_history_reject_invalid_or_scientifically_foreign_runtime(
        self,
    ):
        row, root, _, _, _, _, _ = self.seed_old()
        history = self.state / "job-history" / f"{row['id']}-admet.json"
        original = history.read_bytes()
        for reason, identity in incompatible_identities():
            packet = json.loads(original)
            packet["runtime_identity"] = identity
            write_json_atomic(history, packet)
            with self.service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE compound_recognitions SET runtime_identity=?",
                    (encode(identity),),
                )
            with self.subTest(reason=reason):
                item = self.service.effective_compound(self.project.id, "Compound 1")
                self.assertEqual(item.recognition.status, "unavailable")
                self.assertIsNone(item.smiles)
                self.assertIsNone(read_admet_stage(row, root, state_root=self.state)[0])

    def test_old_release_does_not_bypass_a_new_stereo_epoch(self):
        row, _, _, _, _, _, _ = self.seed_old()
        source = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        with (
            patch.object(
                core, "STEREO_EVIDENCE_VERSION", core.STEREO_EVIDENCE_VERSION + 1
            ),
            patch.object(
                self.service,
                "refresh",
                side_effect=AssertionError("Do not replace raw projection rows"),
            ),
        ):
            self.assertEqual(
                self.service.project(self.project.id).acceptance.state, "historical"
            )
            item = self.service.effective_compound(self.project.id, "Compound 1")
            self.assertFalse(compound_prediction_eligible(item))
        self.assertEqual(self.service.store.job(row["id"]), row)
        self.assertEqual({path: path.read_bytes() for path in source}, source)

    def test_old_producer_can_publish_but_source_and_active_job_cas_still_gate(self):
        row, _, source, prediction, descriptors, record, crop = self.seed_old(
            terminal=False
        )
        before_spec = row["spec"]
        self.service.predictions.put(self.project.id, "Compound 1", prediction)
        self.service.descriptors.put(self.project.id, "Compound 1", descriptors)
        self.recognitions.put(
            self.project.id,
            "Compound 1",
            source=source,
            crop=crop,
            record=record,
            job_id=row["id"],
        )
        self.assertEqual(self.service.store.job(row["id"])["spec"], before_spec)
        before = self.saved_rows()
        with self.assertRaises(WebError) as error:
            self.service.predictions.put(
                self.project.id,
                "Compound 1",
                prediction.model_copy(update={"source_fingerprint": "0" * 64}),
            )
        self.assertEqual(error.exception.code, "admet_binding")
        with self.assertRaises(WebError) as error:
            self.recognitions.put(
                self.project.id,
                "Compound 1",
                source=source,
                crop="0" * 64,
                record=record,
                job_id=row["id"],
            )
        self.assertEqual(error.exception.code, "recognition_source_changed")
        self.assertEqual(self.saved_rows(), before)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete' WHERE id=?", (row["id"],)
            )
        with self.assertRaises(WebError) as error:
            self.service.descriptors.put(self.project.id, "Compound 1", descriptors)
        self.assertEqual(error.exception.code, "admet_binding")

    def test_saved_packets_reject_scientific_schema_engine_and_producer_changes(self):
        row, root, source, _, _, _, _ = self.seed_old()
        inputs = [("Compound 1", source, "CCO")]
        with self.service.store.connect() as connection:
            saved = connection.execute(
                "SELECT payload FROM molecular_descriptors"
            ).fetchone()[0]
        for field in ("runtime", "epoch", "schema", "rdkit", "source", "graph"):
            packet = json.loads(saved)
            if field == "runtime":
                packet["runtime_identity"]["ruleset"]["version"] = "2.0.0"
            elif field == "epoch":
                packet["epoch"] = "0" * 64
            elif field == "schema":
                packet["schema"]["version"] = 2
            elif field == "rdkit":
                packet["observation"]["engine"]["version"] = "foreign"
            elif field == "source":
                packet["observation"]["source_fingerprint"] = "0" * 64
            else:
                packet["observation"]["smiles_sha256"] = "0" * 64
            with self.service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE molecular_descriptors SET payload=?", (encode(packet),)
                )
            with self.subTest(field=field):
                result = self.service.descriptors.summaries(self.project.id, inputs)[
                    "Compound 1"
                ]
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.properties, [])
        with self.service.store.connect(write=True) as connection:
            connection.execute("UPDATE molecular_descriptors SET payload=?", (saved,))
        for reason, identity in incompatible_identities():
            spec = json.loads(row["spec"])
            spec["runtime_identity"] = identity
            with self.service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE jobs SET spec=? WHERE id=?", (encode(spec), row["id"])
                )
            with self.subTest(reason=reason):
                self.assertEqual(
                    self.service.predictions.summaries(self.project.id, inputs)[
                        "Compound 1"
                    ].status,
                    "failed",
                )
                self.assertEqual(
                    self.service.descriptors.summaries(self.project.id, inputs)[
                        "Compound 1"
                    ].status,
                    "failed",
                )
                self.assertIsNone(
                    read_admet_stage(
                        self.service.store.job(row["id"]), root, state_root=self.state
                    )[0]
                )


if __name__ == "__main__":
    unittest.main()
