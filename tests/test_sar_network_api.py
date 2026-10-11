"""Native queue/publication/read/preview/export on controlled identified inputs."""

import unittest
import uuid

import test_sar_api as support
import test_sar_study_analysis as source_support
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.models import Dataset, Molecule

CSV = b"id,smiles,IC50 (nM),t_half (h),target,assay,cells,duration\n1,COc1ccc(Cl)cc1,10,1,T,controlled,C,1h\n2,CCOc1ccc(Cl)cc1,1,2,T,controlled,C,1h\n3,COc1ccc(Br)cc1,0.1,3,T,controlled,C,1h\n4,CCCOc1ccc(Cl)cc1,,4,T,controlled,C,1h\n,CO,0.00001,99,T,controlled,C,1h\nIntermediate 18,CCO,0.00001,99,T,controlled,C,1h\n"


class NetworkAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed

    def import_csv(self, client, data=CSV):
        reply = client.post(
            support.ROOT + "/csv/preview?filename=network.csv", content=data
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        response = client.post(
            support.ROOT + "/datasets/csv",
            json={
                "token": reply.json()["token"],
                "title": "Controlled network",
                "id_column": "id",
                "smiles_column": "smiles",
                "activity_columns": ["IC50 (nM)", "t_half (h)"],
                "target_column": "target",
                "assay_column": "assay",
                "cell_line_column": "cells",
                "duration_column": "duration",
                "request_id": support.nonce(),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def start(self, client, dataset):
        prefix = support.ROOT + "/datasets/" + dataset["id"]
        profile = client.get(prefix + "/profile").json()
        selected = [
            context
            for context in profile["contexts"]
            if context["context"]["duration"] == "1h"
        ]
        body = {
            "request_id": support.nonce(),
            "expected_dataset_revision": dataset["revision"],
            "title": "Single-site network",
            "discover_single_sites": True,
            "policies": [
                {
                    "context_id": context["id"],
                    "direction": "higher" if context["unit"] == "h" else "lower",
                }
                for context in selected
            ],
        }
        response = client.post(prefix + "/studies", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        return self.completed(client, response.json())

    def pair(self, report, left="1", right="2"):
        return next(
            summary
            for summary in report["regions"]
            if summary["reference_label"] == left
            and any(
                right in fragment["molecule_ids"] for fragment in summary["fragments"]
            )
        )

    def test_full_native_network_numbers_missing_activity_pk_and_immutable_exports(
        self,
    ):
        with self.client() as client:
            dataset = self.import_csv(client)
            self.assertEqual((dataset["input_row_count"], dataset["row_count"]), (6, 4))
            job = self.start(client, dataset)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            report = response.json()["report"]
            ids = {
                row["label"]: row["molecule_id"]
                for row in client.get(path + "/rows").json()["items"]
            }
            self.assertEqual(job["total"], 4 + report["strict_pair_count"])
            summary = self.pair(report, right=ids["2"])
            rows = client.get(
                path + "/rows",
                params={
                    "region_id": summary["region"]["id"],
                    "scope": "changes",
                    "page_size": 2,
                },
            )
            self.assertEqual(rows.status_code, 200, rows.text)
            self.assertNotIn("1", [row["label"] for row in rows.json()["items"]])
            self.assertEqual(client.get(path + "/rows?scope=changes").status_code, 422)
            target = ids["2"]
            detail = client.get(
                path + "/preview",
                params={"region_id": summary["region"]["id"], "molecule_id": target},
            )
            self.assertEqual(detail.status_code, 200, detail.text)
            preview = detail.json()
            self.assertEqual(preview["candidate"]["label"], "2")
            by_unit = {context["unit"]: context["id"] for context in report["contexts"]}
            measured = {row["context_id"]: row for row in preview["measurements"]}
            self.assertEqual(measured[by_unit["nM"]]["raw_difference"], -9)
            self.assertEqual(measured[by_unit["h"]]["raw_difference"], 1)
            self.assertGreater(
                preview["candidate"]["properties"]["molecular_weight"], 0
            )
            self.assertIsNone(preview["candidate"]["properties"]["Solubility_AqSolDB"])
            before = client.get(path + "/export?format=json").json()
            missing = client.get(path + "/rows?query=4").json()["items"][0]
            self.assertGreater(missing["properties"]["molecular_weight"], 0)
            self.assertEqual(len(before["input"]["molecules"]), 4)
            self.assertEqual(
                client.get(path + "/export?format=json").json()["input"],
                before["input"],
            )
            self.assertIsNotNone(before["report"]["discovery"])
            drawing = client.get(
                path + "/drawing",
                params={
                    "kind": "molecule",
                    "identifier": target,
                    "region_id": summary["region"]["id"],
                },
            )
            self.assertEqual(drawing.status_code, 200, drawing.text)
            self.assertIn("</svg>", drawing.json()["svg"])

    def test_changed_conditions_do_not_create_a_numeric_pk_or_activity_delta(self):
        with self.client() as client:
            dataset = self.import_csv(
                client, CSV.replace(b"2,T,controlled,C,1h", b"2,T,controlled,C,2h")
            )
            job = self.start(client, dataset)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            report = client.get(path).json()["report"]
            ids = {
                row["label"]: row["molecule_id"]
                for row in client.get(path + "/rows").json()["items"]
            }
            summary = self.pair(report, right=ids["2"])
            target = ids["2"]
            preview = client.get(
                path + "/preview",
                params={"region_id": summary["region"]["id"], "molecule_id": target},
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(
                all(
                    row["raw_difference"] is None
                    and row["comparison"] not in {"better", "worse", "equal"}
                    for row in preview.json()["measurements"]
                )
            )

    def test_legacy_numberless_population_can_publish_a_new_scoped_network(self):
        rows = [
            source_support.molecule(str(index + 1), smiles)
            for index, smiles in enumerate(["COc1ccc(Cl)cc1", "CCOc1ccc(Cl)cc1"])
        ]
        unknown = source_support.molecule("source-structure:x", "CO")
        unknown.update(
            label="编号待确认 S1",
            eligible=False,
            issues=["missing_or_invalid_identifier"],
        )
        rows.append(unknown)
        with self.client() as client:
            service = client.app.state.sar
            dataset = Dataset(
                id=uuid.uuid4().hex,
                title="Legacy controlled",
                source_kind="csv",
                source_sha256="a" * 64,
                row_count=3,
                input_row_count=3,
                eligible_count=2,
                issue_count=1,
                metrics=[source_support.METRIC],
                created_at="2026-01-01T00:00:00Z",
            )
            service.datasets.publish(
                dataset,
                [Molecule.model_validate(row) for row in rows],
                support.nonce(),
                "b" * 64,
            )
            prefix = support.ROOT + "/datasets/" + dataset.id
            context = client.get(prefix + "/profile").json()["contexts"][0]
            response = client.post(
                prefix + "/studies",
                json={
                    "request_id": support.nonce(),
                    "expected_dataset_revision": 1,
                    "title": "Scoped legacy",
                    "discover_single_sites": True,
                    "policies": [{"context_id": context["id"], "direction": "lower"}],
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            job = self.completed(client, response.json())
            report = client.get(support.ROOT + "/jobs/" + job["id"] + "/study").json()[
                "report"
            ]
            self.assertEqual(report["molecule_count"], 2)
            self.assertEqual(job["total"], 2 + report["strict_pair_count"])
