"""Real saved locations, uploaded PDFs, queues and history; no scientific models."""

from __future__ import annotations

import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from test_web_support import ExitRunner, SleepRunner, WebFixture, wait_job

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import decode_spec
from patent_sar_extractor.web.prediction_jobs import enqueue_prediction
from patent_sar_extractor.web.processes import CLIProcessRunner


class StorageLocationTests(WebFixture, unittest.TestCase):
    def test_directory_creation_denial_is_explicit_and_does_not_save_any_location(self):
        with self.client(runner=ExitRunner()) as client:
            original = self.settings(client)
            with patch(
                "patent_sar_extractor.web.data_location_policy.private_directory",
                side_effect=PermissionError("controlled creation denial"),
            ):
                response = self.save(client, "creation-denied")
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["error"]["code"], "storage_unwritable")
            self.assertEqual(self.settings(client), original)
            self.assertFalse((self.root / "uploads-creation-denied").exists())

    def test_export_directory_creation_denial_is_reported_without_partial_files(self):
        with self.client(runner=ExitRunner()) as client:
            project = self.upload(client)
            with patch(
                "patent_sar_extractor.web.saved_exports.private_directory",
                side_effect=PermissionError("controlled export denial"),
            ):
                response = client.post(
                    f"/api/v1/projects/{project['id']}/export", json={"format": "csv"}
                )
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["error"]["code"], "export_storage")
            self.assertFalse((self.state / "runs" / project["id"] / "exports").exists())

    def test_install_operation_snapshots_and_prepares_user_selected_install_prefix(
        self,
    ):
        import json
        import time

        from test_environment_api import CARD, BoundaryRunner

        from patent_sar_extractor.web.analysis_runtime import AnalysisSettings

        config = self.root / "controlled-config"
        with (
            patch.dict("os.environ", {"PATENTSAR_CONFIG_DIR": str(config)}),
            self.client(
                runner=ExitRunner(),
                environment_runner=BoundaryRunner(),
                environment_catalog=lambda: [dict(CARD)],
                analysis_settings=AnalysisSettings(),
            ) as client,
        ):
            current = self.settings(client)
            selected = Path(current["allowed_root"]) / "selected-prefix"
            saved = self.save(client, "installer", install_root=str(selected))
            self.assertEqual(saved.status_code, 200, saved.text)
            response = client.post(
                "/api/v1/environments/operations",
                json={
                    "action": "install",
                    "component_ids": ["base"],
                    "request_id": "controlled-selected-prefix",
                    "expected_revision": saved.json()["revision"],
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            operation = response.json()
            self.assertEqual(operation["install_root"], str(selected))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                operation = client.get(
                    "/api/v1/environments/operations/" + operation["id"]
                ).json()
                if operation["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.02)
            self.assertEqual(operation["status"], "complete", operation)
            plan = json.loads(
                client.app.state.environments.store.row(operation["id"])["spec"]
            )
            self.assertEqual(plan["install_root"], str(selected))
            self.assertTrue((selected / ".x-patentsar-environments.json").is_file())

    def test_invalid_saved_prefix_can_be_repaired_without_claiming_installation_ready(
        self,
    ):
        with self.client(runner=ExitRunner()) as client:
            manager = client.app.state.environments
            current = self.settings(client)
            existing = Path(current["install_root"])
            existing.mkdir(parents=True, mode=0o700)
            original = existing / "unknown.txt"
            original.write_text("preserved unknown contents")
            broken = self.settings(client)
            self.assertFalse(broken["enabled"])
            self.assertTrue(broken["editable"])
            response = self.save(
                client,
                "repaired",
                install_root=str(Path(current["allowed_root"]) / "new-private-prefix"),
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(original.read_text(), "preserved unknown contents")
            self.assertTrue(response.json()["editable"])
            self.assertTrue(response.json()["enabled"])
            self.assertEqual(
                manager.store.settings()["revision"], current["revision"] + 1
            )

    def test_write_probe_failure_rolls_back_all_three_settings_without_chmod_or_cleanup(
        self,
    ):
        with self.client(runner=ExitRunner()) as client:
            original = self.settings(client)
            replacement = str(Path(original["allowed_root"]) / "new-install")
            with patch(
                "patent_sar_extractor.web.data_location_policy.tempfile.mkstemp",
                side_effect=PermissionError("controlled write denial"),
            ):
                response = self.save(client, "denied", install_root=replacement)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.settings(client), original)
            self.assertTrue(
                (self.root / "uploads-denied" / ".x-patentsar-storage.json").is_file()
            )
            self.assertFalse((self.root / "results-denied").exists())
            self.assertFalse(Path(replacement).exists())

    def test_concurrent_saves_have_one_winner_and_do_not_prepare_losing_prefix(self):
        with self.client(runner=ExitRunner()) as client:
            original = self.settings(client)
            bodies = [
                {
                    "install_root": original["install_root"],
                    "upload_root": str(self.root / f"concurrent-upload-{index}"),
                    "result_root": str(self.root / f"concurrent-result-{index}"),
                    "expected_revision": original["revision"],
                }
                for index in range(2)
            ]
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(
                    pool.map(
                        lambda body: client.put(
                            "/api/v1/environments/settings", json=body
                        ),
                        bodies,
                    )
                )
            self.assertEqual(sorted(row.status_code for row in responses), [200, 409])
            loser = next(
                index for index, row in enumerate(responses) if row.status_code == 409
            )
            self.assertFalse(Path(bodies[loser]["upload_root"]).exists())
            self.assertFalse(Path(bodies[loser]["result_root"]).exists())
            self.assertEqual(
                self.settings(client)["revision"], original["revision"] + 1
            )

    def test_verified_ocr_checkpoint_is_relocated_between_configured_result_roots(self):
        from patent_sar_extractor import contracts as core
        from patent_sar_extractor.application.stage_cache import (
            _step_fingerprint,
            _write_step_manifest,
        )
        from patent_sar_extractor.artifact_io import write_json_atomic
        from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata

        with self.client(runner=ExitRunner()) as client:
            self.assertEqual(self.save(client, "one").status_code, 200)
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/jobs"
            first = client.post(endpoint, json={}).json()
            wait_job(client, first["id"], "failed")
            old = client.app.state.queue._spec(first["id"])
            root = Path(old.output_dir)
            cache_path = root / "page_classification/page_ocr_cache.json"
            write_json_atomic(
                cache_path,
                {
                    "metadata": build_cache_metadata(old.pdf_path),
                    "page_texts": {"0": "Controlled original observation"},
                    "ocr_line_map": {},
                },
            )
            classification = root / "page_classification/page_classification.json"
            write_json_atomic(
                classification,
                {
                    **core.artifact_identity(
                        core.PAGE_CLASSIFICATION_SCHEMA,
                        core.PAGE_CLASSIFICATION_SCHEMA_VERSION,
                    ),
                    "page_count": 1,
                    "ocr_cache_path": str(cache_path),
                },
            )
            _write_step_manifest(
                str(classification),
                _step_fingerprint(
                    "classify",
                    pdf_path=old.pdf_path,
                    params={"patent_id": old.patent_id},
                ),
            )
            write_json_atomic(
                root / "pipeline_summary.json",
                {
                    **core.artifact_identity(
                        core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
                    ),
                    "status": "failed",
                    "output_dir": old.output_dir,
                    "patent_id": old.patent_id,
                    "steps": {"classify": {"status": "ok", "page_count": 1}},
                },
            )
            original_cache = cache_path.read_bytes()
            self.assertEqual(self.save(client, "two").status_code, 200)
            resumed = client.post(endpoint, json={"resume_job_id": first["id"]})
            self.assertEqual(resumed.status_code, 202, resumed.text)
            wait_job(client, resumed.json()["id"], "failed")
            new = client.app.state.queue._spec(resumed.json()["id"])
            self.assertEqual(
                (
                    Path(new.output_dir) / "page_classification/page_ocr_cache.json"
                ).read_bytes(),
                original_cache,
            )
            self.assertEqual(cache_path.read_bytes(), original_cache)
            self.assertIn(
                str(Path(new.output_dir)),
                (
                    Path(new.output_dir)
                    / "page_classification/page_classification.json"
                ).read_text(),
            )

    def test_safe_file_root_cannot_resolve_an_ancestor_symlink(self):
        from patent_sar_extractor.web.files import SafeFiles

        real = self.root / "private-real" / "nested"
        real.mkdir(parents=True, mode=0o700)
        original = real / "keep.txt"
        original.write_bytes(b"preserved original")
        link = self.root / "private-link"
        link.symlink_to(real.parent, target_is_directory=True)
        with self.assertRaises(WebError):
            SafeFiles(link / "nested").read("keep.txt", max_bytes=100)
        self.assertEqual(original.read_bytes(), b"preserved original")

    def test_failed_bounded_export_keeps_existing_files_and_publishes_no_partial(self):
        from patent_sar_extractor.web.saved_exports import save_export

        with self.client(runner=ExitRunner()) as client:
            self.assertEqual(self.save(client, "one").status_code, 200)
            project = self.upload(client)
            prefix = self.root / "results-one" / project["id"] / "exports"
            prefix.mkdir(parents=True, mode=0o700)
            existing = prefix / "preserved.csv"
            existing.write_bytes(b"existing user export")
            with (
                patch("patent_sar_extractor.web.saved_exports.MAX_EXPORT_BYTES", 10),
                self.assertRaises(WebError) as failure,
            ):
                save_export(
                    client.app.state.workspace.store,
                    project["id"],
                    "csv",
                    [b"new data exceeds limit"],
                )
            self.assertEqual(failure.exception.status, 413)
            self.assertEqual(existing.read_bytes(), b"existing user export")
            self.assertEqual(
                [path.name for path in prefix.iterdir()], ["preserved.csv"]
            )

    def test_generated_exports_follow_selected_result_root_without_changing_values(
        self,
    ):
        with self.client(runner=ExitRunner()) as client:
            self.assertEqual(self.save(client, "one").status_code, 200)
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/export"
            first = client.post(endpoint, json={"format": "csv"})
            self.assertEqual(first.status_code, 200, first.text)
            first_path = Path(unquote(first.headers["X-PatentSAR-Saved-Path"]))
            self.assertEqual(
                first_path.parent, self.root / "results-one" / project["id"] / "exports"
            )
            self.assertEqual(first_path.read_bytes(), first.content)
            self.assertEqual(
                hashlib.sha256(first.content).hexdigest(),
                first.headers["X-PatentSAR-Content-SHA256"],
            )
            self.assertEqual(self.save(client, "two").status_code, 200)
            second = client.post(endpoint, json={"format": "json"})
            self.assertEqual(second.status_code, 200, second.text)
            second_path = Path(unquote(second.headers["X-PatentSAR-Saved-Path"]))
            self.assertEqual(
                second_path.parent,
                self.root / "results-two" / project["id"] / "exports",
            )
            self.assertEqual(second_path.read_bytes(), second.content)
            self.assertEqual(first_path.read_bytes(), first.content)

    def test_native_paths_with_spaces_remain_readable_and_cannot_be_replaced_by_links(
        self,
    ):
        with self.client(runner=ExitRunner()) as client:
            root = self.root / "uploads with spaces"
            saved = self.save(client, "spaces", upload_root=str(root))
            self.assertEqual(saved.status_code, 200, saved.text)
            project = self.upload(client)
            original = Path(
                client.app.state.workspace.store.project(project["id"])["pdf_rel"]
            )
            content = original.read_bytes()
            path = f"/api/v1/projects/{project['id']}/pages/1/image"
            self.assertEqual(client.get(path).status_code, 200)
            moved = self.root / "kept upload directory"
            root.rename(moved)
            root.symlink_to(moved, target_is_directory=True)
            self.assertIn(client.get(path).status_code, (400, 409))
            self.assertEqual((moved / original.name).read_bytes(), content)

    def test_another_workspace_cannot_adopt_an_existing_managed_prefix(self):
        from patent_sar_extractor.web.data_location_policy import DataLocationPolicy

        with self.client(runner=ExitRunner()) as client:
            self.assertEqual(self.save(client, "one").status_code, 200)
            folder = self.root / "uploads-one"
            marker = (folder / ".x-patentsar-storage.json").read_bytes()
            policy = DataLocationPolicy(self.root / "other-workspace", self.root)
            with self.assertRaises(WebError):
                policy.prepare("uploads", str(folder))
            self.assertEqual(
                (folder / ".x-patentsar-storage.json").read_bytes(), marker
            )

    def settings(self, client):
        response = client.get("/api/v1/environments")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["settings"]

    def save(self, client, label, **changes):
        current = self.settings(client)
        return client.put(
            "/api/v1/environments/settings",
            json={
                "install_root": current["install_root"],
                "upload_root": str(self.root / f"uploads-{label}"),
                "result_root": str(self.root / f"results-{label}"),
                "expected_revision": current["revision"],
                **changes,
            },
        )

    def test_defaults_and_atomic_save_survive_restart_without_moving_old_pdf(self):
        with self.client(runner=ExitRunner()) as client:
            current = self.settings(client)
            self.assertEqual(current["upload_root"], str(self.state / "uploads"))
            self.assertEqual(current["result_root"], str(self.state / "runs"))
            old = self.upload(client)
            stored = client.app.state.workspace.store.project(old["id"])
            original = self.state / stored["pdf_rel"]
            before = original.read_bytes()
            saved = self.save(client, "one")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["revision"], current["revision"] + 1)
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(
                client.get(f"/api/v1/projects/{old['id']}/pages/1/image").status_code,
                200,
            )
            new = self.upload(client)
            new_path = Path(
                client.app.state.workspace.store.project(new["id"])["pdf_rel"]
            )
            self.assertEqual(new_path.parent, self.root / "uploads-one")
            self.assertEqual(
                hashlib.sha256(new_path.read_bytes()).hexdigest(), new["pdf"]["sha256"]
            )
        with self.client(runner=ExitRunner()) as client:
            self.assertEqual(
                self.settings(client)["upload_root"], str(self.root / "uploads-one")
            )
            self.assertEqual(
                client.get(f"/api/v1/projects/{old['id']}/pages/1/image").status_code,
                200,
            )
            self.assertEqual(
                client.get(f"/api/v1/projects/{new['id']}/pages/1/image").status_code,
                200,
            )

    def test_new_run_and_resume_use_new_roots_but_preserve_previous_attempt(self):
        with self.client(runner=ExitRunner()) as client:
            self.assertEqual(self.save(client, "one").status_code, 200)
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/jobs"
            job = client.post(endpoint, json={}).json()
            old = wait_job(client, job["id"], "failed")
            service = client.app.state.workspace
            old_spec = decode_spec(service.store.job(job["id"])["spec"])
            self.assertEqual(
                Path(old_spec.output_dir).parent.parent, self.root / "results-one"
            )
            self.assertEqual(old_spec.workspace_root, str(self.state))
            old_log = (Path(old_spec.output_dir) / "web-process.log").read_bytes()
            self.assertEqual(self.save(client, "two").status_code, 200)
            self.assertTrue(
                client.get(f"/api/v1/jobs/{old['id']}").json()["can_resume"]
            )
            resumed = client.post(endpoint, json={"resume_job_id": job["id"]})
            self.assertEqual(resumed.status_code, 202, resumed.text)
            done = wait_job(client, resumed.json()["id"], "failed")
            spec = decode_spec(service.store.job(done["id"])["spec"])
            self.assertEqual(
                Path(spec.output_dir).parent.parent, self.root / "results-two"
            )
            self.assertEqual(spec.pdf_path, old_spec.pdf_path)
            self.assertEqual(
                (Path(old_spec.output_dir) / "web-process.log").read_bytes(), old_log
            )
            self.assertEqual(
                service.attempts.output(service.store.job(job["id"])),
                Path(old_spec.output_dir),
            )

    def test_prediction_command_uses_workspace_not_result_directory_parent(self):
        with self.client(runner=ExitRunner()) as client:
            self.assertEqual(self.save(client, "one").status_code, 200)
            project = self.upload(client)
            service = client.app.state.workspace
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={}).json()
            wait_job(client, job["id"], "failed")
            original = client.app.state.queue._spec(job["id"])
            command = CLIProcessRunner().command(
                replace(original, admet_only=True, include_admet=True)
            )
            self.assertEqual(command[command.index("--state-dir") + 1], str(self.state))
            with service.store.connect(write=True) as connection:
                identifier = enqueue_prediction(
                    service.store, connection, project["id"]
                )
            new_spec = client.app.state.queue._spec(identifier)
            self.assertEqual(
                Path(new_spec.output_dir).parent.parent, self.root / "results-one"
            )
            self.assertEqual(new_spec.workspace_root, str(self.state))
            client.post(f"/api/v1/jobs/{identifier}/cancel")

    def test_invalid_conflicting_unknown_and_symlink_paths_leave_settings_unchanged(
        self,
    ):
        with self.client(runner=ExitRunner()) as client:
            initial = self.settings(client)
            unknown = self.root / "unknown"
            unknown.mkdir(mode=0o700)
            evidence = unknown / "keep.txt"
            evidence.write_text("user data")
            link = self.root / "linked"
            link.symlink_to(unknown, target_is_directory=True)
            for value in (
                "relative",
                "/mnt/c/Users/Victor/data",
                "E:\\WSL\\data",
                str(self.root / "../escape"),
                str(self.state),
                str(unknown),
                str(link),
                str(self.root),
            ):
                with self.subTest(value=value):
                    response = self.save(client, "unsafe", upload_root=value)
                    self.assertIn(response.status_code, (400, 409), response.text)
                    self.assertEqual(self.settings(client), initial)
                    self.assertEqual(evidence.read_text(), "user data")
            self.assertEqual(
                self.save(
                    client, "same", result_root=str(self.root / "uploads-same")
                ).status_code,
                400,
            )
            self.assertEqual(self.settings(client), initial)
            response = self.save(client, "stale", expected_revision=99)
            self.assertEqual(response.status_code, 409)
            self.assertFalse((self.root / "uploads-stale").exists())

    def test_partial_file_settings_and_untrusted_original_path_are_rejected(self):
        with self.client(runner=ExitRunner()) as client:
            current = self.settings(client)
            partial = client.put(
                "/api/v1/environments/settings",
                json={
                    "install_root": current["install_root"],
                    "upload_root": str(self.root / "partial"),
                    "expected_revision": current["revision"],
                },
            )
            self.assertEqual(partial.status_code, 422)
            project = self.upload(client)
            store = client.app.state.workspace.store
            with store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE projects SET pdf_rel=? WHERE id=?",
                    (str(self.pdf), project["id"]),
                )
            response = client.get(f"/api/v1/projects/{project['id']}/pages/1/image")
            self.assertIn(response.status_code, (400, 409))

    def test_install_only_legacy_client_preserves_configured_file_roots(self):
        with self.client(runner=ExitRunner()) as client:
            first = self.save(client, "one")
            self.assertEqual(first.status_code, 200)
            current = first.json()
            response = client.put(
                "/api/v1/environments/settings",
                json={
                    "install_root": current["install_root"],
                    "expected_revision": current["revision"],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["upload_root"], current["upload_root"])
            self.assertEqual(response.json()["result_root"], current["result_root"])

    def test_active_extraction_keeps_its_snapshot_after_location_change(self):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            first = client.post(
                f"/api/v1/projects/{project['id']}/jobs", json={}
            ).json()
            wait_job(client, first["id"], "running")
            service = client.app.state.workspace
            before = service.store.job(first["id"])["spec"]
            saved = self.save(client, "future")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(service.store.job(first["id"])["spec"], before)
            client.post(f"/api/v1/jobs/{first['id']}/cancel")
            wait_job(client, first["id"], "cancelled")


if __name__ == "__main__":
    unittest.main()
