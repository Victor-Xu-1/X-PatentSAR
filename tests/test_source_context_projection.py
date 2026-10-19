"""Real isolated SQLite/API transport of source scopes, without private inference."""

import hashlib
import json
import unittest
import uuid

from patent_sar_extractor.web.artifacts import _activities
from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.errors import WebError
from tests import test_activity_columns as table_fixture
from tests.test_activity_source_scopes import source_row
from tests.test_web_support import WebFixture, artifact_run


class SourceScopeCorrectionTests(unittest.TestCase):
    def test_known_project_context_can_be_selected_but_cannot_be_forged(self):
        fixture = table_fixture.ActivityColumnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = _activities(source_row(), page_count=5)[0]
        fixture.insert(
            table_fixture.compound("source", [original]),
            table_fixture.compound("blank", []),
        )
        before = fixture.store.compound(fixture.project_id, "blank")["payload"]
        document = fixture.corrections.get(fixture.project_id, "blank")
        copied = original.model_copy(update={"value": "2", "page": None})
        request = CorrectionRequest(
            expected_revision=0,
            expected_source_fingerprint=document.source_fingerprint,
            fields=document.values.model_copy(update={"activities": [copied]}),
        )
        forged = request.model_copy(
            update={
                "fields": request.fields.model_copy(
                    update={
                        "activities": [
                            copied.model_copy(update={"source_scope": "b" * 64})
                        ]
                    }
                )
            }
        )
        with self.assertRaises(WebError) as caught:
            fixture.corrections.put(fixture.project_id, "blank", forged)
        self.assertEqual(caught.exception.code, "correction_activity_origin")
        saved = fixture.corrections.put(fixture.project_id, "blank", request)
        self.assertEqual(saved.values.activities[0].source_scope, original.source_scope)
        self.assertEqual(saved.values.activities[0].value, "2")
        self.assertEqual(
            fixture.store.compound(fixture.project_id, "blank")["payload"], before
        )
        with fixture.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM correction_audit").fetchone()[
                    0
                ],
                1,
            )


class SourceContextSnapshotTests(WebFixture, unittest.TestCase):
    def test_actual_project_results_snapshot_and_profile_keep_two_independent_contexts(
        self,
    ):
        run = artifact_run(
            self.root / "scoped-source", self.pdf, current=True, accepted=False, rows=2
        )
        path = run / "activity/activity_data.json"
        payload = json.loads(path.read_text())
        payload["rows"] = [source_row(1), source_row(2)]
        path.write_text(json.dumps(payload))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.client(import_runs=[run]) as client:
            project = client.get("/api/v1/projects").json()["items"][0]
            base = "/api/v1/projects/" + project["id"]
            upload = client.post(
                base + "/pdf?filename=source.pdf",
                content=self.pdf.read_bytes(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(upload.status_code, 200, upload.text)
            results = client.get(base + "/results").json()
            self.assertEqual(len(results["activity_columns"]), 2)
            response = client.post(
                "/api/v1/sar/datasets/project",
                json={"project_id": project["id"], "request_id": uuid.uuid4().hex},
            )
            self.assertEqual(response.status_code, 201, response.text)
            dataset = response.json()
            self.assertEqual(dataset["source_acceptance"]["state"], "failed")
            self.assertEqual(len(dataset["metrics"]), 2)
            prefix = "/api/v1/sar/datasets/" + dataset["id"]
            molecules = client.get(prefix + "/molecules").json()["items"]
            # This controlled fixture has individually qualified research graphs;
            # that does not promote its failed whole-extraction acceptance above.
            self.assertEqual(sum(len(item["observations"]) for item in molecules), 2)
            profile = client.get(prefix + "/profile")
            self.assertEqual(profile.status_code, 200, profile.text)
            contexts = profile.json()["contexts"]
            self.assertEqual(len(contexts), 2)
            self.assertEqual(
                {c["source_table"] for c in contexts}, {"Table 1", "Table 2"}
            )
            self.assertEqual(client.get(prefix + "/jobs").json()["items"], [])
            exported = client.post(
                base + "/export",
                json={"format": "csv", "compound_ids": [results["items"][0]["id"]]},
            )
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertIn("source_conditions_json", exported.text)
            preview = client.post(
                "/api/v1/sar/csv/preview?filename=exported.csv",
                content=exported.content,
                headers={"Content-Type": "text/csv"},
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            hints = preview.json()
            body = {
                "token": hints["token"],
                "request_id": uuid.uuid4().hex,
                "title": "Native round trip",
                "id_column": hints["suggested_id"],
                "smiles_column": hints["suggested_smiles"],
                "activity_columns": hints["suggested_activities"],
                **hints["mapping_defaults"]["columns"],
                "property_columns": hints["mapping_defaults"]["property_columns"],
                "prediction_columns": hints["mapping_defaults"]["prediction_columns"],
            }
            imported = client.post("/api/v1/sar/datasets/csv", json=body)
            self.assertEqual(
                imported.status_code, 201, f"{imported.text}; generated mapping={body}"
            )
            copied = imported.json()
            self.assertEqual(
                {m["source_scope"] for m in copied["metrics"]},
                {m["source_scope"] for m in dataset["metrics"]},
            )
            records = client.get(
                "/api/v1/sar/datasets/" + copied["id"] + "/molecules"
            ).json()["items"]
            observations = [o for m in records for o in m["observations"]]
            self.assertEqual(len(observations), 2)
            self.assertTrue(all(o["source_kind"] == "imported" for o in observations))
            self.assertTrue(
                all(
                    o["context"]["cell_line"] == "HEK293"
                    and o["context"]["duration"] == "24 h"
                    for o in observations
                )
            )
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
