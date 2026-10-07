"""Correction overlays exercise real SQLite, RDKit and authenticated local APIs."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_web_support import BASE_URL, WebFixture, artifact_run, make_pdf

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.service import WorkspaceService, import_run
from patent_sar_extractor.web.storage import encode, now


class CorrectionTests(WebFixture, unittest.TestCase):
    @contextmanager
    def client(self, **kwargs):
        # This suite isolates correction persistence. The production default
        # auto-ADMET bridge is exercised separately by prediction job tests.
        with super().client(**kwargs) as client:
            client.app.state.workspace.corrections.on_save = None
            yield client

    def setUp(self):
        super().setUp()
        self.run = artifact_run(self.root / "run", self.pdf)
        self.project = import_run(self.state, self.run, pdf_path=self.pdf)
        self.prefix = f"/api/v1/projects/{self.project.id}"
        self.path = self.prefix + "/structures/Compound%201/correction"

    def save(self, client, document, **changes):
        fields = copy.deepcopy(document["values"])
        fields.update(changes)
        return client.put(
            self.path,
            json={
                "expected_revision": document["revision"],
                "expected_source_fingerprint": document["source_fingerprint"],
                "fields": fields,
            },
        )

    def raw(self):
        return WorkspaceService(self.state).store.compound(
            self.project.id, "Compound 1"
        )

    def audit(self):
        with WorkspaceService(self.state).store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM correction_audit ORDER BY revision"
                )
            ]

    def test_read_save_persistence_audit_reset_preserves_raw_artifacts_and_reviews(
        self,
    ):
        raw = self.raw()
        originals = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.run.rglob("*")
            if p.is_file()
        }
        with self.client() as client:
            reviewed = client.put(
                self.prefix + "/reviews/Compound%201",
                json={
                    "decision": "approved",
                    "note": "Separate review",
                    "expected_revision": 0,
                },
            ).json()
            first = client.get(self.path)
            self.assertEqual(first.status_code, 200, first.text)
            original = first.json()
            self.assertEqual(original["revision"], 0)
            self.assertIsNone(original["basis_fingerprint"])
            self.assertFalse(original["stale"])
            self.assertFalse(original["has_changes"])
            self.assertEqual(len(original["source_fingerprint"]), 64)
            saved = self.save(client, original, display_id="Edited label", smiles="CCN")
            self.assertEqual(saved.status_code, 200, saved.text)
            document = saved.json()
            self.assertEqual(document["revision"], 1)
            self.assertTrue(document["has_changes"])
            self.assertEqual(document["original"], original["original"])
            self.assertEqual(
                document["basis_fingerprint"], original["source_fingerprint"]
            )
            row = client.get(self.prefix + "/results?q=Edited%20label").json()["items"][
                0
            ]
            self.assertEqual(row["id"], "Compound 1")
            self.assertEqual(row["smiles"], "CCN")
            self.assertEqual(row["review"], reviewed)
            self.assertEqual(row["source"], json.loads(raw["payload"])["source"])
            self.assertEqual(
                row["confidence"], json.loads(raw["payload"])["confidence"]
            )
            self.assertTrue(
                set(json.loads(raw["payload"])["flags"]).issubset(row["flags"])
            )
            self.assertEqual(
                client.get(self.prefix).json()["acceptance"]["state"], "accepted"
            )
        with self.client() as client:
            restored = client.get(self.path).json()
            self.assertEqual(restored, document)
            reset = self.save(client, restored, **original["original"])
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertEqual(reset.json()["revision"], 2)
            self.assertFalse(reset.json()["has_changes"])
            row = client.get(self.prefix + "/results?q=Compound%201").json()["items"][0]
            self.assertEqual(row["smiles"], "CCO")
            self.assertEqual(row["display_id"], "Compound 1")
        self.assertEqual(self.raw(), raw)
        self.assertEqual(
            originals,
            {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in originals},
        )
        self.assertEqual([r["revision"] for r in self.audit()], [1, 2])
        with WorkspaceService(self.state).store.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0], 1
            )
            for statement in (
                "UPDATE correction_audit SET revision=99",
                "DELETE FROM correction_audit",
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)

    def test_conflicts_do_not_replace_saved_values_or_append_audit(self):
        with self.client() as client:
            original = client.get(self.path).json()
            self.assertEqual(
                self.save(client, original, display_id="Winner").status_code, 200
            )
            stale = self.save(client, original, display_id="Loser")
            self.assertEqual(stale.status_code, 409)
            current = client.get(self.path).json()
            current["source_fingerprint"] = "0" * 64
            mismatch = self.save(client, current, display_id="Wrong basis")
            self.assertEqual(mismatch.status_code, 409)
            self.assertEqual(
                client.get(self.path).json()["values"]["display_id"], "Winner"
            )
        self.assertEqual(len(self.audit()), 1)

    def test_concurrent_first_save_has_one_winner(self):
        from patent_sar_extractor.web.correction_models import CorrectionRequest

        service = WorkspaceService(self.state)
        document = service.get_correction(self.project.id, "Compound 1")

        def save(label):
            fields = document.original.model_copy(update={"display_id": label})
            try:
                return service.put_correction(
                    self.project.id,
                    "Compound 1",
                    CorrectionRequest(
                        expected_revision=0,
                        expected_source_fingerprint=document.source_fingerprint,
                        fields=fields,
                    ),
                ).revision
            except WebError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(save, ("First", "Second"))), [1, 409])
        self.assertEqual(len(self.audit()), 1)

    def test_changed_projection_retains_but_does_not_apply_stale_overlay(self):
        with self.client() as client:
            original = client.get(self.path).json()
            self.assertEqual(
                self.save(
                    client, original, display_id="Old edit", smiles="CCN"
                ).status_code,
                200,
            )
        service = WorkspaceService(self.state)
        service.refresh(self.project.id)
        with self.client() as client:
            document = client.get(self.path).json()
            self.assertNotEqual(
                document["source_fingerprint"], original["source_fingerprint"]
            )
            self.assertTrue(document["stale"])
            self.assertEqual(document["values"]["display_id"], "Old edit")
            row = client.get(self.prefix + "/results?q=Compound%201").json()["items"][0]
            self.assertEqual(row["display_id"], "Compound 1")
            self.assertEqual(row["smiles"], "CCO")
            self.assertTrue(row["correction"]["stale"])
            self.assertEqual(
                client.get(self.prefix + "/results?q=Old%20edit").json()["total"], 0
            )
            self.assertEqual(
                self.save(client, original, display_id="Stale write").status_code, 409
            )
            rebased = self.save(client, document, **document["original"])
            self.assertEqual(rebased.status_code, 200, rebased.text)
            self.assertFalse(rebased.json()["stale"])
            self.assertFalse(rebased.json()["has_changes"])

    def test_changed_run_and_raw_row_change_source_identity(self):
        service = WorkspaceService(self.state)
        first = service.get_correction(self.project.id, "Compound 1")
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET run_root=? WHERE id=?",
                (str(self.run) + "-rerun", self.project.id),
            )
        second = service.get_correction(self.project.id, "Compound 1")
        self.assertNotEqual(first.source_fingerprint, second.source_fingerprint)
        raw = self.raw()
        payload = json.loads(raw["payload"])
        payload["activities"][0]["value"] = "Changed raw value"
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE compounds SET payload=? WHERE project_id=? AND id=?",
                (encode(payload), self.project.id, "Compound 1"),
            )
        third = service.get_correction(self.project.id, "Compound 1")
        self.assertNotEqual(second.source_fingerprint, third.source_fingerprint)

    def test_active_project_job_rejects_edit_without_writes(self):
        service = WorkspaceService(self.state)
        document = service.get_correction(self.project.id, "Compound 1")
        from patent_sar_extractor.web.correction_models import CorrectionRequest

        for status in ("queued", "running"):
            with service.store.connect(write=True) as connection:
                connection.execute(
                    "INSERT INTO jobs(id,project_id,status,created_at,spec) VALUES(?,?,?,?,?)",
                    (status, self.project.id, status, now(), "{}"),
                )
            request = CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=document.original,
            )
            with self.assertRaises(WebError) as raised:
                service.put_correction(self.project.id, "Compound 1", request)
            self.assertEqual(raised.exception.status, 409)
            with service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE jobs SET status='cancelled' WHERE id=?", (status,)
                )
        self.assertEqual(self.audit(), [])

    def test_malformed_fields_and_chemistry_are_rejected(self):
        with self.client() as client:
            original = client.get(self.path).json()
            bad_fields = [
                {"smiles": "C1CC"},
                {"smiles": "*C"},
                {"smiles": "[Fe]"},
                {"smiles": "C C"},
                {"smiles": "[H][H]"},
                {"smiles": "C" * 257},
                {"smiles": "C" * 2049},
                {"display_id": ""},
                {"display_id": "x\nlabel"},
                {"display_id": "x\u202elabel"},
                {"display_id": "x" * 201},
                {"activities": [{"name": "IC50", "value": True}]},
                {"activities": [{"name": "IC50", "value": 10**309}]},
                {"activities": ["not an activity"]},
                {"activities": [{"name": "IC50", "value": [1]}]},
                {"activities": [{"name": "IC50", "value": "x" * 1001}]},
                {"activities": [{"name": "IC50", "value": 1, "target": "x\tbad"}]},
                {"activities": [{"name": "IC50", "value": 1, "page": 2}]},
                {"activities": [{"name": "IC50", "value": 1, "page": True}]},
                {"activities": [{"name": "IC50", "value": 1, "page": "1"}]},
                {"activities": [{"name": "IC50", "value": 1, "bbox": [0, 0, 1, 1]}]},
                {"activities": [{"name": "IC50", "value": 1}] * 101},
                {"activities": [{"name": " ", "value": 1}]},
            ]
            for fields in bad_fields:
                with self.subTest(fields=repr(fields)[:150]):
                    response = self.save(client, original, **fields)
                    self.assertEqual(response.status_code, 422, response.text)
            body = {
                "expected_revision": 0,
                "expected_source_fingerprint": original["source_fingerprint"],
                "fields": original["values"],
            }
            for field, value in (
                ("expected_revision", True),
                ("expected_revision", -1),
                ("expected_source_fingerprint", "invalid"),
            ):
                with self.subTest(field=field, value=value):
                    bad = {**body, field: value}
                    self.assertEqual(client.put(self.path, json=bad).status_code, 422)
            for value in ("NaN", "Infinity", "-Infinity"):
                raw = json.dumps(body).replace('"value": "2"', '"value": ' + value)
                self.assertEqual(
                    client.put(
                        self.path,
                        content=raw,
                        headers={"Content-Type": "application/json"},
                    ).status_code,
                    422,
                )
        self.assertEqual(self.audit(), [])

    def test_effective_search_metrics_targets_redraw_and_export(self):
        raw = self.raw()
        with self.client() as client:
            document = client.get(self.path).json()
            old_row = client.get(self.prefix + "/results?q=Compound%201").json()[
                "items"
            ][0]
            crop_before = client.get(old_row["structure_image_url"]).content
            saved = self.save(
                client,
                document,
                display_id="  =CUSTOM()",
                smiles="NCC",
                activities=[
                    {
                        "name": "=edited",
                        "value": "+0.25",
                        "unit": "nM",
                        "target": "Corrected target",
                        "assay": "Corrected assay",
                        "page": 1,
                    }
                ],
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            results = client.get(
                self.prefix + "/results?target=Corrected%20target&q=%2B0.25"
            ).json()
            self.assertEqual(results["total"], 1)
            self.assertEqual(results["metrics"], ["=edited", "IC50(nM)"])
            self.assertEqual(
                results["targets"], ["Corrected target", "Measured target"]
            )
            row = results["items"][0]
            self.assertEqual(row["smiles"], "NCC")
            self.assertEqual(row["recognition"]["quality_flag"], "manual_correction")
            self.assertIsNone(row["recognition"]["model_fingerprint"])
            self.assertIsNone(row["recognition"]["token_confidence"])
            self.assertIn(hashlib.sha256(b"NCC").hexdigest(), row["redraw_image_url"])
            self.assertEqual(client.get(old_row["redraw_image_url"]).status_code, 409)
            redraw = client.get(row["redraw_image_url"])
            self.assertEqual(redraw.status_code, 200, redraw.text)
            self.assertTrue(redraw.content.startswith(b"\x89PNG"))
            self.assertEqual(
                client.get(row["structure_image_url"]).content, crop_before
            )
            exported = client.post(
                self.prefix + "/export",
                json={"format": "json", "compound_ids": ["Compound 1"]},
            ).json()
            self.assertTrue(exported["review_only"])
            self.assertEqual(exported["acceptance"]["state"], "accepted")
            self.assertEqual(exported["items"][0]["correction"]["revision"], 1)
            self.assertEqual(exported["items"][0]["display_id"], "  =CUSTOM()")
            exported_csv = client.post(
                self.prefix + "/export",
                json={"format": "csv", "compound_ids": ["Compound 1"]},
            )
            csv_row = next(
                csv.DictReader(io.StringIO(exported_csv.content.decode("utf-8-sig")))
            )
            self.assertEqual(csv_row["display_id"], "'  =CUSTOM()")
            self.assertEqual(csv_row["metric"], "'=edited")
            self.assertEqual(csv_row["value"], "'+0.25")
            self.assertEqual(csv_row["correction_revision"], "1")
            self.assertEqual(csv_row["manual_correction"], "True")
            self.assertEqual(csv_row["review_only"], "True")
        self.assertEqual(self.raw(), raw)

    def test_authenticated_csrf_boundaries_and_missing_compounds(self):
        with TestClient(self.app(), base_url=BASE_URL) as client:
            self.assertEqual(client.get(self.path).status_code, 401)
            token = client.get("/api/v1/session").json()["csrf_token"]
            document = client.get(self.path).json()
            body = {
                "expected_revision": 0,
                "expected_source_fingerprint": document["source_fingerprint"],
                "fields": document["values"],
            }
            self.assertEqual(client.put(self.path, json=body).status_code, 403)
            self.assertEqual(
                client.put(
                    self.path,
                    json=body,
                    headers={"Origin": "https://evil.example", "X-CSRF-Token": token},
                ).status_code,
                403,
            )
            self.assertEqual(
                client.put(
                    self.path,
                    json=body,
                    headers={"Origin": BASE_URL, "X-CSRF-Token": "wrong"},
                ).status_code,
                403,
            )
            headers = {"Origin": BASE_URL, "X-CSRF-Token": token}
            self.assertEqual(
                client.get(self.path.replace("Compound%201", "unknown")).status_code,
                404,
            )
            self.assertEqual(
                client.put(
                    self.path.replace("Compound%201", "unknown"),
                    json=body,
                    headers=headers,
                ).status_code,
                404,
            )
            self.assertEqual(
                client.get(self.path.replace(self.project.id, "unknown")).status_code,
                404,
            )
        self.assertEqual(self.audit(), [])

    def test_callback_is_atomic_only_on_effective_smiles_change_and_reset(self):
        from patent_sar_extractor.web.correction_models import (
            CorrectionRequest,
            EditableFields,
        )

        events = []

        def on_save(connection, project_id, compound_id, effective):
            self.assertTrue(connection.in_transaction)
            revision = connection.execute(
                "SELECT revision FROM corrections WHERE project_id=? AND compound_id=?",
                (project_id, compound_id),
            ).fetchone()[0]
            self.assertEqual(revision, effective.correction.revision)
            events.append((project_id, compound_id, effective.smiles))
            connection.execute(
                "INSERT INTO callback_probe VALUES(?)", (effective.smiles,)
            )

        service = WorkspaceService(self.state, correction_on_save=on_save)
        with service.store.connect(write=True) as connection:
            connection.execute("CREATE TABLE callback_probe (smiles TEXT)")

        def put(**changes):
            document = service.get_correction(self.project.id, "Compound 1")
            fields = EditableFields.model_validate(
                {**document.values.model_dump(), **changes}
            )
            return service.put_correction(
                self.project.id,
                "Compound 1",
                CorrectionRequest(
                    expected_revision=document.revision,
                    expected_source_fingerprint=document.source_fingerprint,
                    fields=fields,
                ),
            )

        put(display_id="Only label")
        put(smiles="CCN")
        put(display_id="Still same molecule")
        put(
            **service.get_correction(
                self.project.id, "Compound 1"
            ).original.model_dump()
        )
        self.assertEqual([event[2] for event in events], ["CCN", "CCO"])
        before = self.audit()

        def fail(connection, *_):
            connection.execute("INSERT INTO callback_probe VALUES('rollback')")
            raise WebError(409, "queue_busy", "Controlled transactional queue failure")

        service.corrections.on_save = fail
        with self.assertRaises(WebError):
            put(smiles="CCCl")
        self.assertEqual(self.audit(), before)
        self.assertEqual(
            service.get_correction(self.project.id, "Compound 1").values.smiles, "CCO"
        )
        with service.store.connect() as connection:
            self.assertEqual(
                [
                    row[0]
                    for row in connection.execute("SELECT smiles FROM callback_probe")
                ],
                ["CCN", "CCO"],
            )

    def test_removing_smiles_updates_redraw_and_reset_preserves_original_model_metadata(
        self,
    ):
        with self.client() as client:
            document = client.get(self.path).json()
            original = client.get(self.prefix + "/results?q=Compound%201").json()[
                "items"
            ][0]
            self.assertEqual(self.save(client, document, smiles=None).status_code, 200)
            row = client.get(self.prefix + "/results?q=Compound%201").json()["items"][0]
            self.assertIsNone(row["redraw_image_url"])
            self.assertIsNone(row["smiles"])
            self.assertEqual(client.get(original["redraw_image_url"]).status_code, 404)
            current = client.get(self.path).json()
            self.assertEqual(
                self.save(client, current, **current["original"]).status_code, 200
            )
            row = client.get(self.prefix + "/results?q=Compound%201").json()["items"][0]
            self.assertEqual(row["recognition"], original["recognition"])
            self.assertEqual(row["redraw_image_url"], original["redraw_image_url"])

    def test_pure_source_fingerprint_ignores_review_and_timestamp_changes(self):
        from patent_sar_extractor.web.correction_storage import (
            correction_source_fingerprint,
        )

        service = WorkspaceService(self.state)
        project = service.store.project(self.project.id)
        row = self.raw()
        first = correction_source_fingerprint(project, row)
        project["updated_at"] = "An independent review timestamp"
        row["review_updated_at"] = "Another independent review timestamp"
        payload = json.loads(row["payload"])
        row["payload"] = json.dumps(dict(reversed(list(payload.items()))), indent=2)
        with patch.object(
            service.store,
            "connect",
            side_effect=AssertionError("Fingerprint must be pure"),
        ):
            self.assertEqual(correction_source_fingerprint(project, row), first)
        project["expected_sha256"] = "0" * 64
        project["sha256"] = None
        self.assertNotEqual(correction_source_fingerprint(project, row), first)

    def test_overlay_query_count_does_not_grow_with_result_count(self):
        from patent_sar_extractor.web.correction_models import CorrectionRequest

        service = WorkspaceService(self.state)
        document = service.get_correction(self.project.id, "Compound 1")
        service.put_correction(
            self.project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=document.values.model_copy(update={"display_id": "Overlay row"}),
            ),
        )
        large_run = artifact_run(self.root / "larger-run", self.pdf, rows=100)
        large = service.import_run(large_run, pdf_path=self.pdf)
        large_document = service.get_correction(large.id, "Compound 1")
        service.put_correction(
            large.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=large_document.source_fingerprint,
                fields=large_document.values.model_copy(
                    update={"display_id": "Large overlay row"}
                ),
            ),
        )
        connect = service.store.connect
        statements = []

        @contextmanager
        def traced(*args, **kwargs):
            with connect(*args, **kwargs) as connection:
                connection.set_trace_callback(statements.append)
                yield connection

        counts = []
        with patch.object(service.store, "connect", traced):
            for project_id, total in ((self.project.id, 2), (large.id, 100)):
                statements.clear()
                result = service.results(project_id, page_size=100)
                self.assertEqual(result.total, total)
                edited = next(item for item in result.items if item.id == "Compound 1")
                self.assertTrue(edited.correction.has_changes)
                counts.append(
                    sum(
                        sql.lstrip().upper().startswith(("SELECT", "WITH"))
                        for sql in statements
                    )
                )
        # Two constant Lead-cache metadata reads, never per-compound selection.
        self.assertEqual(counts, [8, 8])
        # One indexed prediction and one descriptor batch, not per-molecule queries.
        self.assertEqual(sum("WITH wanted(" in sql for sql in statements), 2)

    def test_reset_restores_rejected_original_without_promoting_model_metadata(self):
        service = WorkspaceService(self.state)
        row = self.raw()
        payload = json.loads(row["payload"])
        payload["smiles"] = "*C"
        payload["recognition"] = {
            "status": "invalid",
            "quality_flag": "original_rejected",
            "model_fingerprint": "a" * 64,
            "token_confidence": {"minimum": 0.2, "mean": 0.5},
        }
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE compounds SET payload=? WHERE project_id=? AND id=?",
                (encode(payload), self.project.id, "Compound 1"),
            )
        with self.client() as client:
            document = client.get(self.path).json()
            self.assertEqual(
                self.save(client, document, display_id="Label only").status_code, 200
            )
            original = client.get(self.prefix + "/results?q=Label%20only").json()[
                "items"
            ][0]
            self.assertEqual(original["recognition"], payload["recognition"])
            document = client.get(self.path).json()
            self.assertEqual(self.save(client, document, smiles="CCN").status_code, 200)
            corrected = client.get(self.prefix + "/results?q=Label%20only").json()[
                "items"
            ][0]
            self.assertIsNone(corrected["recognition"]["token_confidence"])
            document = client.get(self.path).json()
            reset = self.save(client, document, **document["original"])
            self.assertEqual(reset.status_code, 200, reset.text)
            restored = client.get(self.prefix + "/results?q=Compound%201").json()[
                "items"
            ][0]
            self.assertEqual(restored["smiles"], "*C")
            self.assertEqual(restored["recognition"], payload["recognition"])
            self.assertFalse(restored["correction"]["has_changes"])

    def test_stale_correction_export_is_original_and_reset_removes_review_only_overlay(
        self,
    ):
        with self.client() as client:
            document = client.get(self.path).json()
            self.assertEqual(
                self.save(client, document, display_id="Not formal").status_code, 200
            )
            exported = client.post(
                self.prefix + "/export", json={"format": "json", "compound_ids": []}
            ).json()
            self.assertTrue(exported["review_only"])
            self.assertEqual(exported["manual_corrections"], 1)
        WorkspaceService(self.state).refresh(self.project.id)
        with self.client() as client:
            exported = client.post(
                self.prefix + "/export", json={"format": "json", "compound_ids": []}
            ).json()
            self.assertFalse(exported["review_only"])
            self.assertEqual(exported["manual_corrections"], 0)
            original = next(
                item for item in exported["items"] if item["id"] == "Compound 1"
            )
            self.assertEqual(original["display_id"], "Compound 1")
            self.assertTrue(original["correction"]["stale"])
            document = client.get(self.path).json()
            self.assertEqual(
                self.save(client, document, **document["original"]).status_code, 200
            )
            self.assertEqual(len(self.audit()), 2)

    def test_correction_limits_do_not_truncate_large_original_rows(self):
        service = WorkspaceService(self.state)
        row = self.raw()
        payload = json.loads(row["payload"])
        payload["activities"] *= 101
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE compounds SET payload=? WHERE project_id=? AND id=?",
                (encode(payload), self.project.id, "Compound 1"),
            )
        with self.client() as client:
            response = client.get(self.path)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "correction_limit")
            result = client.get(self.prefix + "/results?q=Compound%201").json()
            self.assertEqual(len(result["items"][0]["activities"]), 101)
        self.assertEqual(self.audit(), [])

    def test_corrupted_manual_chemistry_fails_closed_and_exact_reset_is_audited(self):
        with self.client() as client:
            document = client.get(self.path).json()
            self.assertEqual(self.save(client, document, smiles="CCN").status_code, 200)
        service = WorkspaceService(self.state)
        with service.store.connect(write=True) as connection:
            saved = connection.execute(
                "SELECT fields FROM corrections WHERE project_id=? AND compound_id=?",
                (self.project.id, "Compound 1"),
            ).fetchone()[0]
            fields = json.loads(saved)
            fields["smiles"] = "*C"
            connection.execute(
                "UPDATE corrections SET fields=? WHERE project_id=? AND compound_id=?",
                (encode(fields), self.project.id, "Compound 1"),
            )
        with self.client() as client:
            response = client.get(self.prefix + "/results")
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "unsupported_molecule")
            document = client.get(self.path).json()
            reset = self.save(client, document, **document["original"])
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertEqual(client.get(self.prefix + "/results").status_code, 200)
        self.assertEqual(len(self.audit()), 2)

    def test_effective_molecule_consumer_uses_corrected_authority_without_pdf_pages(
        self,
    ):
        from patent_sar_extractor.web.correction_models import CorrectionRequest

        rotated = make_pdf(self.root / "rotated.pdf", rotation=90)
        run = artifact_run(self.root / "unrotated-source", rotated, rendered=False)
        service = WorkspaceService(self.state)
        project = service.import_run(run, pdf_path=rotated)
        document = service.get_correction(project.id, "Compound 1")
        service.put_correction(
            project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=document.values.model_copy(
                    update={"display_id": "Consumer edit", "smiles": "CCCl"}
                ),
            ),
        )
        with (
            patch(
                "patent_sar_extractor.web.result_queries.open_pdf",
                side_effect=AssertionError("Molecule consumer must not open the PDF"),
            ),
            patch(
                "patent_sar_extractor.web.result_queries.rendered_box",
                side_effect=AssertionError(
                    "Molecule consumer must not load coordinate pages"
                ),
            ),
        ):
            rows = service.effective_compounds(project.id)
            self.assertEqual([row.id for row in rows], ["Compound 1", "Compound 2"])
            edited = next(row for row in rows if row.id == "Compound 1")
            self.assertEqual(edited.display_id, "Consumer edit")
            self.assertEqual(edited.smiles, "CCCl")
            self.assertTrue(edited.correction.has_changes)
            self.assertEqual(edited.source.bbox, [20, 40, 120, 140])
        projected = service.results(project.id)
        displayed = next(row for row in projected.items if row.id == "Compound 1")
        self.assertEqual(displayed.source.bbox, [60, 20, 160, 120])
        self.assertEqual(displayed.smiles, edited.smiles)


if __name__ == "__main__":
    unittest.main()
