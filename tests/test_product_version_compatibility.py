"""Canonical release identity, stage-cache and queue compatibility regressions."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_job_attempts as attempt_cases
from product_version_support import OLD_RELEASE, incompatible_identities
from test_web_support import WebFixture

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.stage_cache import (
    _fingerprint_matches,
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.attempts import ARTIFACTS
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import decode_spec
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.processes import (
    runtime_identity,
    runtime_identity_matches,
)
from patent_sar_extractor.web.storage import encode


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


if __name__ == "__main__":
    unittest.main()
