from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_web_support import WebFixture, artifact_run, make_pdf

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.models import ReviewRequest
from patent_sar_extractor.web.pdf import rendered_box
from patent_sar_extractor.web.reviews import put_review
from patent_sar_extractor.web.service import WorkspaceService, import_run


class ResultTests(WebFixture, unittest.TestCase):
    def test_paged_results_only_transform_visible_boxes_and_preserve_rotation(self):
        pdf = make_pdf(self.root / "rotated.pdf", rotation=90)
        run = artifact_run(self.root / "paged-run", pdf, rows=30, rendered=False)
        imported = import_run(self.state, run, pdf_path=pdf)
        with self.client() as client, patch(
            "patent_sar_extractor.web.service.rendered_box", wraps=rendered_box
        ) as normalize:
            response = client.get(
                f"/api/v1/projects/{imported.id}/results?page=2&page_size=3"
            )
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["total"], 30)
            self.assertEqual(len(data["items"]), 3)
            self.assertEqual(data["items"][0]["id"], "Compound 27")
            self.assertEqual(data["items"][0]["source"]["bbox"], [60, 20, 160, 120])
            self.assertEqual(normalize.call_count, 3)

    def test_pagination_does_not_hide_out_of_document_source_pages(self):
        run = artifact_run(self.root / "invalid-page-run", self.pdf, rows=30)
        imported = import_run(self.state, run, pdf_path=self.pdf)
        service = WorkspaceService(self.state)
        row = service.store.compound(imported.id, "Compound 1")
        payload = json.loads(row["payload"])
        payload["source"]["page"] = 999
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE compounds SET payload=? WHERE project_id=? AND id=?",
                (json.dumps(payload), imported.id, "Compound 1"),
            )
        with self.client() as client:
            response = client.get(
                f"/api/v1/projects/{imported.id}/results?page=1&page_size=1"
            )
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["error"]["code"], "invalid_geometry")

    def test_activity_order_search_filters_pagination_and_downloads(self):
        run = artifact_run(self.root / "run", self.pdf, current=False, rows=12)
        imported = import_run(self.state, run)
        with self.client() as client:
            prefix = f"/api/v1/projects/{imported.id}"
            response = client.get(prefix + "/results?page=1&page_size=5").json()
            self.assertEqual(response["total"], 12)
            self.assertEqual(
                [r["id"] for r in response["items"]],
                [f"Compound {n}" for n in range(12, 7, -1)],
            )
            self.assertEqual(response["metrics"], ["IC50(nM)"])
            self.assertEqual(response["targets"], ["Measured target"])
            self.assertEqual(
                client.get(prefix + "/results?confidence=high").json()["total"], 0
            )
            self.assertEqual(
                client.get(prefix + "/results?target=other").json()["total"], 0
            )
            self.assertEqual(
                client.get(prefix + "/results?q=Compound%2012").json()["total"], 1
            )
            for query in ("page=0", "page_size=101", "confidence=fake", "review=fake"):
                self.assertEqual(
                    client.get(prefix + "/results?" + query).status_code, 422
                )
            download = client.post(
                prefix + "/export?q=Compound%2012",
                json={"format": "json", "compound_ids": []},
            )
            self.assertTrue(download.json()["review_only"])
            self.assertEqual(len(download.json()["items"]), 1)
            self.assertIn("attachment", download.headers["content-disposition"])
            self.assertEqual(
                client.post(
                    prefix + "/export",
                    json={"format": "json", "compound_ids": ["unknown"]},
                ).status_code,
                404,
            )

    def test_current_identity_and_both_deterministic_qa_checks(self):
        for mode in (
            "accepted",
            "old_rules",
            "bad_qa",
            "missing_qa",
            "marker",
            "bare_smiles",
            "bad_mode",
        ):
            run = artifact_run(self.root / mode, self.pdf)
            if mode == "old_rules":
                path = run / "activity/activity_data.json"
                data = json.loads(path.read_text())
                data["ruleset"]["version"] = "2.0.0"
                path.write_text(json.dumps(data))
            elif mode == "bad_qa":
                path = run / "final_qa_report.json"
                data = json.loads(path.read_text())
                data["ok"] = False
                path.write_text(json.dumps(data))
            elif mode == "missing_qa":
                (run / "final_qa_report.json").unlink()
            elif mode == "marker":
                (run / "STRICT_ACCEPTANCE_FAILED.json").write_text('{"stage":"bind"}')
            elif mode == "bare_smiles":
                (run / "smiles/smiles_results.json").write_text("[]")
            elif mode == "bad_mode":
                path = run / "structure_bindings/bindings.json"
                data = json.loads(path.read_text())
                data["execution_mode"] = "diagnostic_unvalidated"
                path.write_text(json.dumps(data))
            project = import_run(self.state, run, pdf_path=self.pdf)
            expected = (
                "accepted"
                if mode == "accepted"
                else "failed"
                if mode in {"bad_qa", "marker"}
                else "historical"
            )
            self.assertEqual(project.acceptance.state, expected, mode)

    def test_review_conflict_audit_and_core_artifacts_unchanged(self):
        run = artifact_run(self.root / "run", self.pdf, current=False)
        imported = import_run(self.state, run)
        originals = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob("*.json")
        }
        with self.client() as client:
            prefix = f"/api/v1/projects/{imported.id}"
            first = client.put(
                prefix + "/reviews/Compound%201",
                json={
                    "decision": "approved",
                    "note": "Observed manually",
                    "expected_revision": 0,
                },
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["revision"], 1)
            second = client.put(
                prefix + "/reviews/Compound%201",
                json={"decision": "rejected", "note": "stale", "expected_revision": 0},
            )
            self.assertEqual(second.status_code, 409)
            self.assertEqual(
                client.get(prefix).json()["acceptance"]["state"], "historical"
            )
            results = client.get(prefix + "/results?review=approved").json()
            self.assertEqual(results["total"], 1)
            self.assertNotEqual(results["items"][0]["confidence"]["level"], "high")
            self.assertEqual(
                client.put(
                    prefix + "/reviews/not-active",
                    json={"decision": "approved", "note": "", "expected_revision": 0},
                ).status_code,
                404,
            )
        self.assertEqual(
            originals,
            {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in originals},
        )
        service = WorkspaceService(self.state)
        with service.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0], 1
            )
        with self.client() as client:
            self.assertEqual(
                client.get(
                    f"/api/v1/projects/{imported.id}/results?review=approved"
                ).json()["total"],
                1,
            )

    def test_concurrent_first_review_has_exactly_one_winner(self):
        run = artifact_run(self.root / "run", self.pdf, current=False)
        imported = import_run(self.state, run)
        store = WorkspaceService(self.state).store

        def save(note):
            try:
                return put_review(
                    store,
                    imported.id,
                    "Compound 1",
                    ReviewRequest(decision="approved", note=note, expected_revision=0),
                ).revision
            except WebError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, ("first", "second")))
        self.assertEqual(sorted(results), [1, 409])
        with store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0], 1
            )

    def test_csv_formula_escaping_and_review_only_labels(self):
        run = artifact_run(self.root / "run", self.pdf, current=False)
        path = run / "activity/activity_data.json"
        data = json.loads(path.read_text())
        data["rows"][0]["activity_values"] = {"=danger": "\t=SUM(1,2)"}
        path.write_text(json.dumps(data))
        imported = import_run(self.state, run)
        with self.client() as client:
            prefix = f"/api/v1/projects/{imported.id}"
            client.put(
                prefix + "/reviews/Compound%202",
                json={
                    "decision": "approved",
                    "note": "  @evil",
                    "expected_revision": 0,
                },
            )
            response = client.post(
                prefix + "/export", json={"format": "csv", "compound_ids": []}
            )
            self.assertEqual(response.status_code, 200)
            rows = list(
                csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
            )
            self.assertEqual(rows[0]["metric"], "'=danger")
            self.assertEqual(rows[0]["value"], "'\t=SUM(1,2)")
            self.assertEqual(rows[0]["review_note"], "'  @evil")
            self.assertEqual(rows[0]["review_only"], "True")
            self.assertEqual(rows[0]["acceptance_state"], "historical")

    def test_real_historical_artifacts_are_read_only_and_never_current(self):
        run = Path("/home/victor_1/.local/state/patent-sar-extractor/runs/WO2026156070")
        if not run.is_dir():
            self.skipTest("Operator historical run is unavailable on this environment")
        files = list(run.glob("*/*.json"))
        before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
        project = import_run(self.state, run)
        self.assertEqual(project.acceptance.state, "historical")
        self.assertFalse(project.pdf.available)
        self.assertEqual(project.pdf.page_count, 1553)
        self.assertEqual(project.summary.confirmed, 0)
        self.assertGreater(project.summary.activity_rows, 1000)
        with self.client() as client:
            response = client.get(
                f"/api/v1/projects/{project.id}/results?page_size=10"
            ).json()
            self.assertEqual(response["items"][0]["id"], "Compound 1")
            self.assertTrue(
                all(r["confidence"]["level"] != "high" for r in response["items"])
            )
            self.assertEqual(
                client.post(f"/api/v1/projects/{project.id}/jobs", json={}).status_code,
                409,
            )
            crop_url = response["items"][0]["structure_image_url"]
            if crop_url:
                self.assertEqual(client.get(crop_url).status_code, 200)
        self.assertEqual(
            before, {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
        )
