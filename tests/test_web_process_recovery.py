"""Recovery regressions with real owned processes; no scientific acceptance claims."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_web_support import SleepRunner, WebFixture

from patent_sar_extractor import contracts
from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import encode, now

OLD_BOOT = "11111111-1111-4111-8111-111111111111"


class ProcessRecoveryTests(WebFixture, unittest.TestCase):
    def owned_job(self):
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "input.pdf", None
        )
        runner = SleepRunner()
        queue = JobQueue(service, runner, 30)
        job = queue.enqueue(project.id, JobRequest())
        spec = decode_spec(service.store.job(job.id)["spec"])
        identity = runner.start(spec)
        self.addCleanup(lambda: runner.stop(identity, spec, grace_seconds=0.1))
        return service, queue, spec, identity

    def test_previous_kernel_boot_never_signals_current_reused_pid(self):
        _, queue, spec, identity = self.owned_job()
        previous = replace(identity, boot_id=OLD_BOOT)
        self.assertNotEqual(previous.boot_id, queue.runner.boot_id)
        with (
            patch("patent_sar_extractor.web.processes.os.kill") as kill,
            patch("patent_sar_extractor.web.processes.os.killpg") as killpg,
        ):
            self.assertTrue(queue.runner.stop(previous, spec, grace_seconds=0))
            kill.assert_not_called()
            killpg.assert_not_called()
        self.assertIsNone(queue.runner._children[identity.pid].poll())

    def test_invalid_boot_or_foreign_arguments_remain_blocked(self):
        _, queue, spec, identity = self.owned_job()
        with (
            patch("patent_sar_extractor.web.processes.os.kill") as kill,
            patch("patent_sar_extractor.web.processes.os.killpg") as killpg,
        ):
            self.assertFalse(
                queue.runner.stop(replace(identity, boot_id="unknown"), spec)
            )
            self.assertFalse(
                queue.runner.stop(
                    replace(identity, boot_id="00000000-0000-0000-0000-000000000000"),
                    spec,
                )
            )
            self.assertFalse(
                queue.runner.stop(
                    replace(identity, boot_id=OLD_BOOT, argv=["foreign"]), spec
                )
            )
            self.assertFalse(
                queue.runner.stop(
                    replace(identity, boot_id=OLD_BOOT, pgid=identity.pid + 1), spec
                )
            )
            self.assertFalse(
                queue.runner.stop(
                    replace(identity, boot_id=OLD_BOOT, pid=2**40, pgid=2**40), spec
                )
            )
            kill.assert_not_called()
            killpg.assert_not_called()
        self.assertIsNone(queue.runner._children[identity.pid].poll())

    def test_running_old_boot_becomes_resumable_and_preserves_identity_evidence(self):
        service, queue, spec, identity = self.owned_job()
        previous = replace(identity, boot_id=OLD_BOOT)
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=?,identity=? WHERE id=?",
                (now(), encode(previous.to_dict()), spec.job_id),
            )
        queue.reconcile()
        recovered = service.job(spec.job_id)
        self.assertEqual(recovered.status, "interrupted")
        self.assertTrue(recovered.can_resume)
        self.assertEqual(recovered.error.code, "server_interrupted")
        self.assertIsNone(queue.runner._children[identity.pid].poll())
        receipts = list((service.store.root / "job-recovery").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        proof = json.loads(receipts[0].read_text())
        self.assertEqual(proof["identity"], previous.to_dict())
        self.assertEqual(proof["job_id"], spec.job_id)
        self.assertEqual(proof["reason"], "previous_kernel_boot")

    def test_already_blocked_interruption_is_rechecked_and_seeds_partial_ocr_only(self):
        service, queue, spec, identity = self.owned_job()
        previous = replace(identity, boot_id=OLD_BOOT)
        original_root = Path(spec.output_dir)
        cache = {
            "metadata": build_cache_metadata(spec.pdf_path, 1),
            "page_texts": {"0": "Controlled partial source observation"},
            "ocr_line_map": {},
        }
        classification = original_root / "page_classification"
        classification.mkdir()
        (classification / "page_ocr_cache.json").write_text(json.dumps(cache))
        old_cache = (classification / "page_ocr_cache.json").read_bytes()
        summary = {
            **contracts.artifact_identity(
                contracts.RUN_SUMMARY_SCHEMA, contracts.RUN_SUMMARY_SCHEMA_VERSION
            ),
            "status": "running",
            "steps": {"classify": {"status": "running"}},
        }
        (original_root / "pipeline_summary.json").write_text(json.dumps(summary))
        (original_root / "final_qa_report.json").write_text(
            '{"acceptance":{"ok":false}}'
        )
        stamp = now()
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='interrupted',started_at=?,finished_at=?,identity=?,error=? WHERE id=?",
                (
                    stamp,
                    stamp,
                    encode(previous.to_dict()),
                    encode({"code": "ownership_unverified", "message": "blocked"}),
                    spec.job_id,
                ),
            )
        row = service.store.job(spec.job_id)
        queue._seal(row, "interrupted", stamp)
        history_path = service.store.root / "job-history" / f"{spec.job_id}.json"
        history = history_path.read_bytes()
        queue.reconcile()
        self.assertTrue(service.job(spec.job_id).can_resume)
        resumed = queue.enqueue(spec.project_id, JobRequest(resume_job_id=spec.job_id))
        resumed_spec = decode_spec(service.store.job(resumed.id)["spec"])
        new_root = Path(resumed_spec.output_dir)
        self.assertNotEqual(new_root, original_root)
        self.assertEqual(
            json.loads(
                (new_root / "page_classification/page_ocr_cache.json").read_bytes()
            ),
            cache,
        )
        self.assertFalse((new_root / "final_qa_report.json").exists())
        self.assertFalse((new_root / "pipeline_summary.json").exists())
        self.assertEqual(history_path.read_bytes(), history)
        self.assertEqual(
            hashlib.sha256(
                (classification / "page_ocr_cache.json").read_bytes()
            ).digest(),
            hashlib.sha256(old_cache).digest(),
        )
        before = list((service.store.root / "job-recovery").glob("*.json"))
        queue.reconcile()
        self.assertEqual(
            list((service.store.root / "job-recovery").glob("*.json")), before
        )

    def test_malformed_retained_identity_is_not_cleared(self):
        service, queue, spec, identity = self.owned_job()
        malformed = {**identity.to_dict(), "pid": True, "boot_id": OLD_BOOT}
        raw = encode(malformed)
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='interrupted',identity=?,error=?,finished_at=? WHERE id=?",
                (
                    raw,
                    encode({"code": "ownership_unverified", "message": "blocked"}),
                    now(),
                    spec.job_id,
                ),
            )
        queue.reconcile()
        self.assertFalse(service.job(spec.job_id).can_resume)
        self.assertEqual(service.store.job(spec.job_id)["identity"], raw)
        self.assertIsNone(queue.runner._children[identity.pid].poll())

    def test_unreadable_same_boot_process_is_not_assumed_dead(self):
        _, queue, spec, identity = self.owned_job()
        with (
            patch("patent_sar_extractor.web.processes._process", return_value=None),
            patch("patent_sar_extractor.web.processes.os.kill") as kill,
            patch("patent_sar_extractor.web.processes.os.killpg") as killpg,
        ):
            self.assertFalse(queue.runner.stop(identity, spec))
            kill.assert_not_called()
            killpg.assert_not_called()
        self.assertIsNone(queue.runner._children[identity.pid].poll())

    def test_corrupt_existing_receipt_is_preserved_and_blocks_publication(self):
        service, queue, spec, identity = self.owned_job()
        previous = replace(identity, boot_id=OLD_BOOT)
        raw = encode(previous.to_dict())
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='interrupted',identity=?,error=?,finished_at=? WHERE id=?",
                (
                    raw,
                    encode({"code": "ownership_unverified", "message": "blocked"}),
                    now(),
                    spec.job_id,
                ),
            )
        folder = service.store.root / "job-recovery"
        folder.mkdir(mode=0o700)
        receipt = (
            folder / f"{spec.job_id}-{hashlib.sha256(raw.encode()).hexdigest()}.json"
        )
        receipt.write_text("[]")
        queue.reconcile()
        self.assertFalse(service.job(spec.job_id).can_resume)
        self.assertEqual(service.store.job(spec.job_id)["identity"], raw)
        self.assertEqual(receipt.read_text(), "[]")


if __name__ == "__main__":
    unittest.main()
