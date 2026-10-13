"""Independent inputs through native workers, parent proof, reads and exports."""

from __future__ import annotations

import csv
import io
import unittest
from dataclasses import replace

import test_sar_api as support
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.preview_source import load_source
from patent_sar_extractor.web.sar.study_preview import verified_preview


class SARIntervalAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    region = support.SARAPITests.region

    def test_different_endpoints_preserve_raw_intervals_through_native_study(self):
        for endpoint, left, right, direction, fold, delta, legacy_v3 in (
            ("IC50 (nM)", ">10", "<10", "lower", None, None, "better"),
            ("DC50 (pM)", ">=0.01", "<0.01", "lower", None, None, "better"),
            ("Dmax (%)", "<80", ">=80", "higher", None, None, "better"),
            ("IC50 (nM)", "10 nM", "0.002 µM", "lower", 5.0, -8.0, "indeterminate"),
            ("DC50 (pM)", ">10 pM", "<0.01 nM", "lower", None, None, "indeterminate"),
            ("Dmax (%)", "70 %", "80%", "higher", 80 / 70, 10.0, "indeterminate"),
        ):
            with self.subTest(endpoint=endpoint), self.client() as client:
                data = io.StringIO(newline="")
                writer = csv.writer(data)
                writer.writerow(
                    ["id", "smiles", endpoint, "target", "assay", "cells", "duration"]
                )
                writer.writerows(
                    [
                        ["R0", "COc1ccc(Cl)cc1", left, "T", "controlled", "C", "2h"],
                        ["R1", "CCOc1ccc(Cl)cc1", right, "T", "controlled", "C", "2h"],
                        ["R2", "CCOc1ccc(Br)cc1", "30", "T", "controlled", "C", "2h"],
                    ]
                )
                preview = client.post(
                    support.ROOT + "/csv/preview?filename=interval.csv",
                    content=data.getvalue().encode(),
                )
                self.assertEqual(preview.status_code, 200, preview.text)
                reply = client.post(
                    support.ROOT + "/datasets/csv",
                    json={
                        "token": preview.json()["token"],
                        "title": "Independent interval case",
                        "id_column": "id",
                        "smiles_column": "smiles",
                        "activity_columns": [endpoint],
                        "target_column": "target",
                        "assay_column": "assay",
                        "cell_line_column": "cells",
                        "duration_column": "duration",
                        "request_id": support.nonce(),
                    },
                )
                self.assertEqual(reply.status_code, 201, reply.text)
                dataset = reply.json()
                region = self.region(client, dataset)
                prefix = support.ROOT + "/datasets/" + dataset["id"]
                profile = client.get(prefix + "/profile").json()
                context = profile["contexts"][0]
                reply = client.post(
                    prefix + "/studies",
                    json={
                        "request_id": support.nonce(),
                        "expected_dataset_revision": 1,
                        "title": "Native interval proof",
                        "region_ids": [region["id"]],
                        "policies": [
                            {"context_id": context["id"], "direction": direction}
                        ],
                    },
                )
                self.assertEqual(reply.status_code, 202, reply.text)
                job = self.completed(client, reply.json())
                path = support.ROOT + "/jobs/" + job["id"] + "/study"
                exported = client.get(path + "/export?format=json")
                self.assertEqual(exported.status_code, 200, exported.text)
                archive = exported.json()
                self.assertEqual(archive["input"]["schema"], 5)
                report = archive["report"]
                self.assertEqual(
                    report["candidate_policy"], "strict-context-pareto-units-v3"
                )
                self.assertEqual(report["matched_pair_count"], 1)
                self.assertEqual(report["comparable_pair_count"], 1)
                fronts = {row["label"]: row["pareto_front"] for row in report["rows"]}
                self.assertEqual(fronts["R1"], 1)
                self.assertEqual(fronts["R0"], 2)
                rows = client.get(prefix + "/molecules").json()["items"]
                candidate = next(row for row in rows if row["label"] == "R1")
                params = {"region_id": region["id"], "molecule_id": candidate["id"]}
                reply = client.get(path + "/preview", params=params)
                self.assertEqual(reply.status_code, 200, reply.text)
                result = reply.json()
                self.assertEqual(result["pair"]["comparison"], "better")
                self.assertEqual(result["pair"]["fold_change"], fold)
                measured = result["measurements"][0]
                self.assertEqual(measured["comparison"], "better")
                self.assertEqual(measured["reference_values"], [left])
                self.assertEqual(measured["candidate_values"], [right])
                self.assertEqual(measured["raw_difference"], delta)
                self.assertEqual(measured["evidence_basis"], "recorded_context")
                matrix = client.get(
                    path + "/matrix",
                    params={
                        "reference_id": region["molecule_id"],
                        "region_id": region["id"],
                        "molecule_id": candidate["id"],
                    },
                )
                self.assertEqual(matrix.status_code, 200, matrix.text)
                self.assertEqual(
                    matrix.json()["previews"][0]["measurements"], result["measurements"]
                )
                # Explicitly exercise the archived-read adapter without editing
                # any stored input, result, pair, task or receipt.
                queue = client.app.state.sar_queue
                source = load_source(queue, job["id"])
                legacy = replace(source, packet={**source.packet, "schema": 2})
                old_view = verified_preview(
                    queue, legacy, region["id"], candidate["id"]
                )
                self.assertEqual(
                    old_view.data.measurements[0].comparison, "indeterminate"
                )
                legacy = replace(source, packet={**source.packet, "schema": 3})
                old_view = verified_preview(
                    queue, legacy, region["id"], candidate["id"]
                )
                self.assertEqual(old_view.data.measurements[0].comparison, legacy_v3)
                self.assertEqual(
                    client.get(path + "/export?format=json").content, exported.content
                )
                wrong = next(row for row in rows if row["label"] == "R2")
                self.assertEqual(
                    client.get(
                        path + "/preview", params={**params, "molecule_id": wrong["id"]}
                    ).status_code,
                    422,
                )


if __name__ == "__main__":
    unittest.main()
