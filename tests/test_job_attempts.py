"""Attempt isolation and real checkpoint transport, SQLite and core CLI evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from test_web_support import ExitRunner, WebFixture, wait_job

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata
from patent_sar_extractor.web.attempts import ARTIFACTS, OCR_PATH, CheckpointCopy
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import STAGES, Error, JobRequest
from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.processes import CLIProcessRunner
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import encode, now


class AttemptTests(WebFixture, unittest.TestCase):
    def draft(self):
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "native.pdf", None
        )
        queue = JobQueue(service, ExitRunner(), 60)
        job = queue.enqueue(project.id, JobRequest())
        return (
            service,
            project,
            queue,
            job,
            decode_spec(service.store.job(job.id)["spec"]),
        )

    def summary(self, spec, *, status="failed", steps=None):
        write_json_atomic(
            Path(spec.output_dir) / "pipeline_summary.json",
            {
                **core.artifact_identity(
                    core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
                ),
                "status": status,
                "output_dir": spec.output_dir,
                "patent_id": spec.patent_id,
                "steps": steps
                or {
                    "classify": {"status": "ok", "page_count": 1},
                    "activity": {"status": "failed"},
                },
            },
        )

    def finish(self, service, queue, job, *, status="failed"):
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job.id),
            )
        queue._finish(
            job.id,
            status,
            Error(code="controlled_failure", message="Controlled fixture boundary"),
        )

    def classification(self, spec):
        root = Path(spec.output_dir)
        write_json_atomic(
            root / OCR_PATH,
            {
                "metadata": build_cache_metadata(spec.pdf_path),
                "page_texts": {"0": "Original observed native page"},
                "ocr_line_map": {},
            },
        )
        path, schema, version = ARTIFACTS["classify"]
        write_json_atomic(
            root / path,
            {
                **core.artifact_identity(schema, version),
                "page_count": 1,
                "ocr_cache_path": str(root / OCR_PATH),
            },
        )
        _write_step_manifest(
            str(root / path),
            _step_fingerprint(
                "classify", pdf_path=spec.pdf_path, params={"patent_id": spec.patent_id}
            ),
        )

    def test_terminal_history_is_write_once_and_independent_of_mutated_output(self):
        service, project, queue, job, spec = self.draft()
        self.summary(spec)
        self.finish(service, queue, job)
        original = service.job(job.id).model_dump()
        self.assertTrue(original["history_available"])
        history = self.state / "job-history" / f"{job.id}.json"
        content = history.read_bytes()
        self.summary(
            spec, status="complete", steps={name: {"status": "ok"} for name in STAGES}
        )
        self.assertEqual(service.job(job.id).model_dump(), original)
        queue._finish(job.id, "complete", None)
        self.assertEqual(history.read_bytes(), content)
        self.assertEqual(
            WorkspaceService(self.state).job(job.id).model_dump(), original
        )
        with service.store.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_unidentified_original_keeps_empty_patent_id_but_requires_pdf_identity(
        self,
    ):
        service, _, _, job, spec = self.draft()
        self.assertEqual(spec.patent_id, "")
        payload = json.loads(service.store.job(job.id)["spec"])
        self.assertEqual(decode_spec(encode(payload)).sha256, spec.sha256)
        for field in ("job_id", "project_id", "pdf_path", "output_dir", "sha256"):
            with self.subTest(field=field), self.assertRaises(WebError):
                decode_spec(encode({**payload, field: ""}))

    def test_corrupt_terminal_progress_is_unavailable_not_promoted(self):
        service, _, queue, job, spec = self.draft()
        self.summary(spec)
        self.finish(service, queue, job)
        path = self.state / "job-history" / f"{job.id}.json"
        payload = json.loads(path.read_text())
        stage = next(value for value in payload["stages"] if value["name"] == "smiles")
        stage["progress"] = {
            "completed": 2,
            "total": 1,
            "cache_hits": 0,
            "failures": 0,
            "device": "cpu",
            "peak_rss_mb": 10.0,
        }
        write_json_atomic(path, payload)
        result = service.job(job.id)
        self.assertFalse(result.history_available)
        self.assertEqual(result.stages, [])

    def test_existing_attempt_directory_is_never_reused_or_overwritten(self):
        service, project, queue, job, spec = self.draft()
        self.summary(spec)
        self.finish(service, queue, job)
        original = (Path(spec.output_dir) / "pipeline_summary.json").read_bytes()
        with patch(
            "patent_sar_extractor.web.jobs.uuid.uuid4", return_value=uuid.UUID(job.id)
        ):
            with self.assertRaises(WebError) as failure:
                queue.enqueue(project.id, JobRequest())
        self.assertEqual(failure.exception.code, "attempt_exists")
        self.assertEqual(
            (Path(spec.output_dir) / "pipeline_summary.json").read_bytes(), original
        )
        self.assertEqual(service.job(job.id).status, "failed")

    def test_history_filename_rejects_noncanonical_job_id(self):
        service, _, queue, job, _ = self.draft()
        row = service.store.job(job.id)
        for identifier in ("../outside", "a" * 31, "A" * 32, "a" * 32 + "/file"):
            with self.subTest(identifier=identifier):
                invalid = {**row, "id": identifier}
                self.assertFalse(service.attempts.read(invalid).available)
                with self.assertRaises(WebError):
                    service.attempts.seal(invalid, "failed", now())
        self.assertFalse((self.state / "job-history").exists())

    def test_legacy_shared_output_has_explicitly_unavailable_history_for_all_jobs(self):
        service, project, queue, job, spec = self.draft()
        self.summary(spec)
        self.finish(service, queue, job)
        record = json.loads(service.store.job(job.id)["spec"])
        record.pop("attempt_version")
        record.pop("resume_job_id")
        other = uuid.uuid4().hex
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET spec=? WHERE id=?", (encode(record), job.id)
            )
            connection.execute(
                "INSERT INTO jobs(id,project_id,status,created_at,finished_at,spec) VALUES(?,?,'cancelled',?,?,?)",
                (other, project.id, now(), now(), encode({**record, "job_id": other})),
            )
        self.summary(
            spec, status="complete", steps={name: {"status": "ok"} for name in STAGES}
        )
        for identifier, status in ((job.id, "failed"), (other, "cancelled")):
            result = service.job(identifier)
            self.assertEqual(result.status, status)
            self.assertFalse(result.history_available)
            self.assertFalse(result.can_resume)
            self.assertEqual(result.stages, [])

    def test_unique_legacy_output_can_expose_only_its_reliable_original_summary(self):
        service, project, queue, job, spec = self.draft()
        self.summary(spec)
        self.finish(service, queue, job)
        record = json.loads(service.store.job(job.id)["spec"])
        record.pop("attempt_version")
        record.pop("resume_job_id")
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET spec=? WHERE id=?", (encode(record), job.id)
            )
        result = service.job(job.id)
        self.assertTrue(result.history_available)
        self.assertEqual(result.stages[1].status, "failed")
        self.summary(
            spec, status="complete", steps={name: {"status": "ok"} for name in STAGES}
        )
        self.assertFalse(service.job(job.id).history_available)

    def test_legacy_alternate_path_spelling_is_not_unique_history(self):
        service, project, queue, job, spec = self.draft()
        self.summary(spec)
        self.finish(service, queue, job)
        record = json.loads(service.store.job(job.id)["spec"])
        record.pop("attempt_version")
        record.pop("resume_job_id")
        other = uuid.uuid4().hex
        alias = f"{spec.output_dir}/../{Path(spec.output_dir).name}"
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET spec=? WHERE id=?", (encode(record), job.id)
            )
            connection.execute(
                "INSERT INTO jobs(id,project_id,status,created_at,finished_at,spec) VALUES(?,?,'failed',?,?,?)",
                (
                    other,
                    project.id,
                    now(),
                    now(),
                    encode({**record, "job_id": other, "output_dir": alias}),
                ),
            )
        self.assertFalse(service.job(job.id).history_available)
        self.assertFalse(service.job(job.id).can_resume)

    def test_resume_copies_verified_content_and_relocates_paths_without_hardlinks(self):
        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        self.summary(spec)
        root = Path(spec.output_dir)
        write_json_atomic(root / "STRICT_ACCEPTANCE_FAILED.json", {"stage": "activity"})
        write_json_atomic(root / "final_qa_report.json", {"ok": False})
        original = {
            path: path.read_bytes() for path in root.rglob("*") if path.is_file()
        }
        self.finish(service, queue, job)
        resumed = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        new_spec = decode_spec(service.store.job(resumed.id)["spec"])
        target = Path(new_spec.output_dir)
        self.assertNotEqual(target, root)
        self.assertEqual(target.name, resumed.id)
        self.assertFalse((target / "pipeline_summary.json").exists())
        self.assertFalse((target / "STRICT_ACCEPTANCE_FAILED.json").exists())
        self.assertFalse((target / "final_qa_report.json").exists())
        source = root / ARTIFACTS["classify"][0]
        copied = target / ARTIFACTS["classify"][0]
        self.assertEqual(
            json.loads(copied.read_text())["ocr_cache_path"], str(target / OCR_PATH)
        )
        self.assertNotEqual(source.stat().st_ino, copied.stat().st_ino)
        self.assertEqual(copied.stat().st_nlink, 1)
        copied.write_text("New attempt overwrite")
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.assertEqual(service.job(job.id).status, "failed")

    def test_normal_rerun_uses_same_verified_transport_but_force_is_fresh(self):
        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        self.summary(spec)
        self.finish(service, queue, job)
        before = service.job(job.id).model_dump()
        first = queue.enqueue(project.id, JobRequest())
        target = Path(decode_spec(service.store.job(first.id)["spec"]).output_dir)
        self.assertNotEqual(str(target), spec.output_dir)
        self.assertTrue((target / ARTIFACTS["classify"][0]).is_file())
        self.assertEqual(
            decode_spec(service.store.job(first.id)["spec"]).source_ocr_cache, ""
        )
        self.assertFalse((target / "pipeline_summary.json").exists())
        self.assertEqual(service.job(job.id).model_dump(), before)
        queue.cancel(first.id)
        fresh = queue.enqueue(project.id, JobRequest(force=True))
        fresh_root = Path(decode_spec(service.store.job(fresh.id)["spec"]).output_dir)
        self.assertFalse((fresh_root / ARTIFACTS["classify"][0]).exists())
        self.assertEqual(
            decode_spec(service.store.job(fresh.id)["spec"]).source_ocr_cache, ""
        )

    def test_resume_uses_compatible_raw_ocr_without_promoting_old_derived_rules(self):
        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        root = Path(spec.output_dir)
        ocr_file = root / OCR_PATH
        cache = json.loads(ocr_file.read_text())
        cache["metadata"]["ruleset"]["version"] = "2.0.1"
        cache["metadata"].pop("observation_contract")
        write_json_atomic(ocr_file, cache)
        for stage, collection in (("activity", "rows"), ("locate", "selected_pages")):
            relative, schema, version = ARTIFACTS[stage]
            write_json_atomic(
                root / relative,
                {
                    **core.artifact_identity(schema, version),
                    collection: [0] if stage == "locate" else [],
                },
            )
            _write_step_manifest(
                str(root / relative),
                _step_fingerprint(
                    stage,
                    pdf_path=spec.pdf_path,
                    dependencies=[str(root / ARTIFACTS["classify"][0]), str(ocr_file)],
                ),
            )
        write_json_atomic(root / "structure_pages/crop_regions.json", {})
        self.summary(
            spec,
            steps={
                "classify": {"status": "ok"},
                "activity": {"status": "ok"},
                "locate": {"status": "ok"},
                "structures": {"status": "failed"},
            },
        )
        original = ocr_file.read_bytes()
        self.finish(service, queue, job)
        resumed = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        target = Path(decode_spec(service.store.job(resumed.id)["spec"]).output_dir)
        self.assertEqual((target / OCR_PATH).read_bytes(), original)
        self.assertTrue((target / ARTIFACTS["locate"][0]).is_file())
        self.assertEqual(ocr_file.read_bytes(), original)
        self.assertEqual(service.job(job.id).status, "failed")

    def test_failed_smiles_resume_transports_raw_cache_not_failed_output_or_qa(self):
        import sqlite3

        from patent_sar_extractor.core.ocsr.smiles_cache import SmilesCache

        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        root = Path(spec.output_dir)
        previous = ARTIFACTS["classify"][0]
        for stage, collection in (
            ("activity", "rows"),
            ("locate", "selected_pages"),
            ("structures", "structures"),
            ("bind", "final_bindings"),
        ):
            relative, schema, version = ARTIFACTS[stage]
            payload = {
                **core.artifact_identity(schema, version),
                collection: [0] if stage == "locate" else [],
            }
            if stage == "bind":
                payload["execution_mode"] = "production_activity_led"
            write_json_atomic(root / relative, payload)
            _write_step_manifest(
                str(root / relative),
                _step_fingerprint(
                    stage, pdf_path=spec.pdf_path, dependencies=[str(root / previous)]
                ),
            )
            if stage == "locate":
                write_json_atomic(root / "structure_pages/crop_regions.json", {})
            previous = relative
        cache_file = root / "smiles/smiles_cache.sqlite"
        cache = SmilesCache(str(cache_file))
        identity = "c" * 64
        engine = f"decimer:raw-v{core.OCSR_OBSERVATION_VERSION}:{identity}"
        cache.save_result(
            "a" * 64,
            engine,
            {"status": "success", "model_fingerprint": identity, "raw_smiles": "CCO"},
        )
        cache.save_result("b" * 64, engine, {"status": "timeout", "raw_smiles": None})
        with sqlite3.connect(cache_file) as connection:
            observation = connection.execute(
                "SELECT * FROM smiles_observations WHERE image_hash=?", ("a" * 64,)
            ).fetchone()
        source = cache_file.read_bytes()
        write_json_atomic(root / ARTIFACTS["smiles"][0], {"records": ["failed output"]})
        write_json_atomic(root / "final_qa_report.json", {"ok": False})
        self.summary(
            spec,
            steps={
                name: {"status": "failed" if name == "smiles" else "ok"}
                for name in ARTIFACTS
            },
        )
        self.finish(service, queue, job)
        resumed = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        target = Path(decode_spec(service.store.job(resumed.id)["spec"]).output_dir)
        copied = target / "smiles/smiles_cache.sqlite"
        with sqlite3.connect(copied) as connection:
            self.assertEqual(
                connection.execute("SELECT * FROM smiles_observations").fetchall(),
                [observation],
            )
        self.assertNotEqual(copied.stat().st_ino, cache_file.stat().st_ino)
        self.assertEqual(copied.stat().st_nlink, 1)
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
        self.assertEqual(cache_file.read_bytes(), source)
        self.assertFalse((target / ARTIFACTS["smiles"][0]).exists())
        self.assertFalse((target / "final_qa_report.json").exists())
        self.assertEqual(service.job(job.id).status, "failed")

    def test_changed_dependency_or_old_contract_is_not_copied(self):
        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        root = Path(spec.output_dir)
        primary = root / ARTIFACTS["activity"][0]
        write_json_atomic(
            primary,
            {
                **core.artifact_identity(
                    core.ACTIVITY_SCHEMA, core.ACTIVITY_SCHEMA_VERSION
                ),
                "rows": [],
            },
        )
        fp = _step_fingerprint(
            "activity",
            pdf_path=spec.pdf_path,
            dependencies=[str(root / ARTIFACTS["classify"][0])],
        )
        fp["dependency_sha256"][str(root / ARTIFACTS["classify"][0])] = "0" * 64
        _write_step_manifest(str(primary), fp)
        self.summary(
            spec,
            steps={
                "classify": {"status": "ok"},
                "activity": {"status": "ok"},
                "locate": {"status": "failed"},
            },
        )
        self.finish(service, queue, job)
        fresh = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        target = Path(decode_spec(service.store.job(fresh.id)["spec"]).output_dir)
        self.assertTrue((target / ARTIFACTS["classify"][0]).is_file())
        self.assertFalse((target / ARTIFACTS["activity"][0]).exists())
        queue.cancel(fresh.id)
        manifest = Path(str(root / ARTIFACTS["classify"][0]) + ".manifest.json")
        payload = json.loads(manifest.read_text())
        payload["ruleset"]["version"] = "0.0.0"
        write_json_atomic(manifest, payload)
        next_attempt = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        target = Path(
            decode_spec(service.store.job(next_attempt.id)["spec"]).output_dir
        )
        self.assertFalse((target / ARTIFACTS["classify"][0]).exists())

    def test_traversal_is_refused_and_the_failed_new_attempt_is_retained(self):
        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        self.summary(spec)
        root = Path(spec.output_dir)
        manifest = Path(str(root / ARTIFACTS["classify"][0]) + ".manifest.json")
        payload = json.loads(manifest.read_text())
        payload["fingerprint"]["dependency_sha256"] = {"../outside.json": "0" * 64}
        write_json_atomic(manifest, payload)
        old = manifest.read_bytes()
        self.finish(service, queue, job)
        fresh = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        self.assertEqual(fresh.status, "failed")
        self.assertEqual(fresh.error.code, "unsafe_asset")
        self.assertTrue(
            Path(decode_spec(service.store.job(fresh.id)["spec"]).output_dir).is_dir()
        )
        self.assertEqual(manifest.read_bytes(), old)
        self.assertTrue(fresh.can_resume)

    def test_copy_budget_failure_retains_both_attempts_without_running_cli(self):
        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        self.summary(spec)
        self.finish(service, queue, job)
        with patch("patent_sar_extractor.web.attempts.MAX_COPY_BYTES", 1):
            fresh = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        self.assertEqual(fresh.status, "failed")
        self.assertEqual(fresh.error.code, "checkpoint_limit")
        self.assertEqual(queue.runner._children, {})
        self.assertTrue(Path(spec.output_dir).is_dir())

    def test_checkpoint_cannot_redirect_the_cli_to_a_foreign_ocr_file(self):
        service, project, queue, job, spec = self.draft()
        self.classification(spec)
        root = Path(spec.output_dir)
        primary = root / ARTIFACTS["classify"][0]
        payload = json.loads(primary.read_text())
        payload["ocr_cache_path"] = "/etc/foreign-ocr.json"
        write_json_atomic(primary, payload)
        self.summary(spec)
        self.finish(service, queue, job)
        fresh = queue.enqueue(project.id, JobRequest(resume_job_id=job.id))
        self.assertEqual(fresh.status, "failed")
        self.assertEqual(fresh.error.code, "unsafe_asset")
        self.assertEqual(queue.runner._children, {})

    def test_symlink_parent_is_not_a_verified_owned_workspace(self):
        service, project, queue, job, spec = self.draft()
        self.summary(spec)
        self.finish(service, queue, job)
        alias = self.state / "runs" / project.id / "alias"
        alias.symlink_to(Path(spec.output_dir).parent, target_is_directory=True)
        record = json.loads(service.store.job(job.id)["spec"])
        record.pop("attempt_version")
        record["output_dir"] = str(alias / Path(spec.output_dir).name)
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET spec=? WHERE id=?", (encode(record), job.id)
            )
        result = service.job(job.id)
        self.assertFalse(result.can_resume)
        self.assertFalse(result.history_available)
        self.assertEqual(result.stages, [])

    def test_smiles_provenance_images_are_copied_without_changing_chemistry(self):
        import fitz

        source = self.root / "source-run"
        source.mkdir(mode=0o700)
        target = self.root / "target-run"
        paths = [
            "structures/original.png",
            "smiles/preprocessed/masked.png",
            "smiles/preprocessed/normalized.png",
        ]
        with fitz.open(self.pdf) as document:
            image = document[0].get_pixmap().tobytes("png")
        for relative in paths:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(image)
        record = {
            "cpd_id": "Compound 7",
            "smiles": "C[C@H](O)Cl",
            "canonical_smiles": "C[C@H](O)Cl",
            "model_fingerprint": "exact-model-content-fingerprint",
            "chemical_note": str(source) + "/not-a-path-field",
            "structure_image": str(source / paths[0]),
            "ocsr_structure_image": str(source / paths[1]),
            "engine_attempts": [
                {
                    "input_image": str(source / paths[1]),
                    "smiles": "C[C@H](O)Cl",
                    "input_image_sha256": hashlib.sha256(image).hexdigest(),
                },
                {
                    "input_image": str(source / paths[2]),
                    "smiles": "C[C@H](O)Cl",
                    "input_image_sha256": hashlib.sha256(image).hexdigest(),
                },
            ],
        }
        original = encode(record)
        transport = CheckpointCopy(source, target)
        transport.images(record)
        moved = transport.relocate(record)
        self.assertEqual(encode(record), original)
        for key in ("smiles", "canonical_smiles", "model_fingerprint", "chemical_note"):
            self.assertEqual(moved[key], record[key])
        self.assertEqual(moved["structure_image"], str(target / paths[0]))
        self.assertEqual(moved["ocsr_structure_image"], str(target / paths[1]))
        for index in range(2):
            self.assertEqual(
                moved["engine_attempts"][index]["smiles"],
                record["engine_attempts"][index]["smiles"],
            )
            self.assertEqual(
                moved["engine_attempts"][index]["input_image_sha256"],
                record["engine_attempts"][index]["input_image_sha256"],
            )
            self.assertEqual(
                Path(moved["engine_attempts"][index]["input_image"]).read_bytes(), image
            )
        for relative in paths:
            self.assertEqual((target / relative).read_bytes(), image)
            self.assertNotEqual(
                (target / relative).stat().st_ino, (source / relative).stat().st_ino
            )
            self.assertEqual((target / relative).stat().st_nlink, 1)

    def test_smiles_input_image_cannot_escape_or_follow_a_symlink(self):
        source = self.root / "source-run"
        source.mkdir(mode=0o700)
        (source / "smiles").mkdir(mode=0o700)
        outside = self.root / "outside.png"
        outside.write_bytes(b"outside private input")
        link = source / "smiles" / "normalized.png"
        link.symlink_to(outside)
        transport = CheckpointCopy(source, self.root / "target-run")
        for value in (str(outside), "../outside.png", str(link)):
            with self.subTest(value=value), self.assertRaises(WebError):
                transport.images({"engine_attempts": [{"input_image": value}]})
        self.assertEqual(transport.content, {})

    def test_nested_first_crop_creates_every_target_ancestor_privately(self):
        source = self.root / "nested-source"
        source.mkdir(mode=0o700)
        relative = "structures/.chunks/chunk_001/structure_0050.png"
        image = source / relative
        image.parent.mkdir(parents=True)
        image.write_bytes(b"unchanged structure crop")
        transport = CheckpointCopy(source, self.root / "nested-target")
        transport.images({"structure_image": str(image)})
        for ancestor in (
            transport.target,
            transport.target / "structures",
            transport.target / "structures/.chunks",
            transport.target / "structures/.chunks/chunk_001",
        ):
            self.assertEqual(ancestor.stat().st_mode & 0o777, 0o700)
        self.assertEqual((transport.target / relative).read_bytes(), image.read_bytes())

    def test_real_cli_failure_resume_reuses_classification_and_preserves_old_attempt(
        self,
    ):
        config = self.root / "operator-config"
        config.mkdir(mode=0o700)

        class LocalCLI(CLIProcessRunner):
            def environment(self, spec):
                env = super().environment(spec)
                env.update(
                    {
                        "PATENTSAR_CONFIG_DIR": str(config),
                        "PATENTSAR_BASE_PYTHON": sys.executable,
                        "PATENTSAR_PADDLEX_OCR_URL": "off",
                        "LLM_API_KEY": "",
                    }
                )
                return env

        with self.client(runner=LocalCLI(), job_timeout_seconds=60) as client:
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/jobs"
            first = client.post(endpoint, json={}).json()
            original = wait_job(client, first["id"], "failed", timeout=60)
            self.assertTrue(original["history_available"])
            old_root = Path(client.app.state.queue._spec(first["id"]).output_dir)
            before = {
                str(path.relative_to(old_root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in old_root.rglob("*")
                if path.is_file()
            }
            response = client.post(endpoint, json={"resume_job_id": first["id"]})
            self.assertEqual(response.status_code, 202, response.text)
            fresh = wait_job(client, response.json()["id"], "failed", timeout=60)
            target = Path(client.app.state.queue._spec(fresh["id"]).output_dir)
            self.assertNotEqual(target, old_root)
            self.assertIn(
                "[classify] 已存在，跳过", (target / "web-process.log").read_text()
            )
            self.assertEqual(client.get(f"/api/v1/jobs/{first['id']}").json(), original)
            after = {
                str(path.relative_to(old_root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in old_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            self.assertEqual(fresh["stages"][1]["status"], "failed")
            self.assertNotEqual(
                client.get(f"/api/v1/projects/{project['id']}").json()["acceptance"][
                    "state"
                ],
                "accepted",
            )
