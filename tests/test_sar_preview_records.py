"""Unselected source measurements remain visible, never statistical conclusions."""

import unittest
from dataclasses import replace

import test_sar_api as support
from test_web_support import WebFixture

from patent_sar_extractor.core.sar.study_contexts import context_catalog
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.preview_records import recorded_measurements
from patent_sar_extractor.web.sar.preview_source import load_source
from patent_sar_extractor.web.sar.study_models import StudyContext
from patent_sar_extractor.web.sar.study_preview import verified_preview


class SARPreviewRecordTests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    region = support.SARAPITests.region

    def test_one_sided_missing_reading_is_retained_and_unknown_context_is_refused(self):
        source = {"id": "P1", "observations": []}
        candidate = {
            "id": "P2",
            "observations": [
                {
                    "metric_id": "pk",
                    "value": "",
                    "unit": "h",
                    "context": {"assay": "PK"},
                }
            ],
        }
        raw = context_catalog([source, candidate], [{"id": "pk", "name": "t1/2"}])
        context = StudyContext.model_validate(raw[0])
        records = recorded_measurements(source, candidate, [context], set())
        self.assertEqual(records[0].reference_values, [])
        self.assertEqual(records[0].candidate_values, [""])
        self.assertEqual(
            recorded_measurements(source, candidate, [context], {context.id}), []
        )
        with self.assertRaises(WebError) as raised:
            recorded_measurements(source, candidate, [], set())
        self.assertEqual(raised.exception.status, 409)

    def prepare(
        self, client, repeated=False, *, declared_units=False, metric="IC50 (nM)"
    ):
        text = (
            "id,smiles,IC50 (nM),CL (mL/min/kg),Ymin,target,assay,cells,duration\n"
            "P1,COc1ccc(Cl)cc1,10,2,15,T,binding,C,2h\n"
            "P2,CCOc1ccc(Cl)cc1,1,5,20,T,binding,C,2h\n"
            "P3,CCCOc1ccc(Cl)cc1,0.1,<6,,T,binding,C,2h\n"
            "P4,CCOc1ccc(Br)cc1,0.01,1,5,T,binding,C,2h\n"
        )
        if repeated:
            text += "P3,CCCOc1ccc(Cl)cc1,0.1,>9,,T,binding,C,2h\n"
        if declared_units:
            lines = text.splitlines()
            for index in range(1, len(lines)):
                fields = lines[index].split(",")
                fields[3] += " mL/min/kg"
                lines[index] = ",".join(fields)
            text = "\n".join(lines) + "\n"
        response = client.post(
            support.ROOT + "/csv/preview?filename=source-records.csv",
            content=text.encode(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        response = client.post(
            support.ROOT + "/datasets/csv",
            json={
                "token": response.json()["token"],
                "title": "Source measurements",
                "id_column": "id",
                "smiles_column": "smiles",
                "activity_columns": ["IC50 (nM)", "CL (mL/min/kg)", "Ymin"],
                "target_column": "target",
                "assay_column": "assay",
                "cell_line_column": "cells",
                "duration_column": "duration",
                "request_id": support.nonce(),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        dataset = response.json()
        region = self.region(client, dataset)
        prefix = support.ROOT + "/datasets/" + dataset["id"]
        contexts = client.get(prefix + "/profile").json()["contexts"]
        chosen = next(item for item in contexts if item["name"] == metric)
        response = client.post(
            prefix + "/studies",
            json={
                "request_id": support.nonce(),
                "expected_dataset_revision": dataset["revision"],
                "title": "Complete comparison preview",
                "region_ids": [region["id"]],
                "policies": [{"context_id": chosen["id"], "direction": "lower"}],
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        job = self.completed(client, response.json())
        path = support.ROOT + "/jobs/" + job["id"] + "/study"
        rows = client.get(prefix + "/molecules").json()["items"]
        return path, region, contexts, {row["label"]: row for row in rows}

    def test_unselected_pk_and_response_are_raw_and_archive_is_unchanged(self):
        with self.client() as client:
            path, region, contexts, rows = self.prepare(client)
            original = client.get(path + "/export?format=json").content
            response = client.get(
                path + "/preview",
                params={"region_id": region["id"], "molecule_id": rows["P2"]["id"]},
            )
            self.assertEqual(response.status_code, 200, response.text)
            preview = response.json()
            self.assertEqual(len(preview["measurements"]), 1)
            recorded = preview.get("recorded_measurements", [])
            self.assertEqual(len(recorded), 2)
            names = {item["id"]: item["name"] for item in contexts}
            by_name = {names[item["context_id"]]: item for item in recorded}
            self.assertEqual(by_name["CL (mL/min/kg)"]["reference_values"], ["2"])
            self.assertEqual(by_name["CL (mL/min/kg)"]["candidate_values"], ["5"])
            self.assertEqual(by_name["Ymin"]["candidate_values"], ["20"])
            self.assertEqual(
                by_name["CL (mL/min/kg)"]["difference"],
                {"status": "comparable", "value": 3.0},
            )
            self.assertEqual(
                by_name["Ymin"]["difference"],
                {"status": "indeterminate", "value": None},
            )
            for item in recorded:
                self.assertNotIn("comparison", item)
                self.assertNotIn("raw_difference", item)
                self.assertNotIn("evidence_basis", item)
            matrix = client.get(
                path + "/matrix",
                params={
                    "reference_id": region["molecule_id"],
                    "region_id": region["id"],
                    "molecule_id": rows["P2"]["id"],
                },
            )
            self.assertEqual(matrix.status_code, 200, matrix.text)
            self.assertEqual(
                matrix.json()["previews"][0]["recorded_measurements"], recorded
            )
            queue = client.app.state.sar_queue
            source = load_source(queue, path.split("/")[-2])
            for schema in (2, 3, 4, 5):
                legacy = replace(source, packet={**source.packet, "schema": schema})
                old = verified_preview(
                    queue, legacy, region["id"], rows["P2"]["id"]
                ).data
                self.assertTrue(
                    all(
                        "difference" not in item.model_dump()
                        for item in old.recorded_measurements
                    )
                )
            self.assertEqual(client.get(path + "/export?format=json").content, original)

    def test_censored_repeats_and_missing_values_are_not_filled_or_ranked(self):
        with self.client() as client:
            path, region, contexts, rows = self.prepare(client, repeated=True)
            response = client.get(
                path + "/preview",
                params={"region_id": region["id"], "molecule_id": rows["P3"]["id"]},
            )
            self.assertEqual(response.status_code, 200, response.text)
            recorded = response.json().get("recorded_measurements", [])
            self.assertEqual(len(recorded), 2)
            names = {item["id"]: item["name"] for item in contexts}
            by_name = {names[item["context_id"]]: item for item in recorded}
            self.assertEqual(
                by_name["CL (mL/min/kg)"]["candidate_values"], ["<6", ">9"]
            )
            self.assertEqual(by_name["Ymin"]["candidate_values"], ["", ""])

    def test_same_region_changed_pool_and_previews_keep_the_frozen_background(self):
        with self.client() as client:
            path, region, _contexts, rows = self.prepare(client)
            response = client.get(
                path + "/rows", params={"region_id": region["id"], "scope": "changes"}
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                [item["label"] for item in response.json()["items"]], ["P2", "P3"]
            )
            for label in ("P2", "P3"):
                response = client.get(
                    path + "/preview",
                    params={
                        "region_id": region["id"],
                        "molecule_id": rows[label]["id"],
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["pair"]["match_status"], "matched")
            response = client.get(
                path + "/preview",
                params={"region_id": region["id"], "molecule_id": rows["P4"]["id"]},
            )
            self.assertEqual(response.status_code, 422)
