"""Native shared workflow, full-population colors and immutable raw exports."""

import unittest

import test_sar_api as support
import test_sar_potency_bands as potency_support
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.study_activity_view import prepare_activity
from patent_sar_extractor.web.sar.study_models import StudyReport


class LogPotencyWorkflowTests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    run_study = potency_support.SARPotencyTests.run_study

    def test_native_log_study_rows_charts_filters_exports_and_archive_semantics(self):
        with self.client() as client:
            path, context = self.run_study(
                client,
                ["10"] * 9 + ["9", "8", "7", ""],
                metric="pIC50",
                direction="higher",
            )
            archived = client.get(path + "/export?format=json").json()
            before = client.get(path + "/export?format=json").content
            self.assertEqual(archived["input"]["schema"], 6)
            dataset_path = (
                support.ROOT + "/datasets/" + archived["input"]["dataset"]["id"]
            )
            original_rows = client.get(dataset_path + "/molecules").json()["items"]
            self.assertTrue(
                all(
                    obs["unit"] is None
                    for row in original_rows
                    for obs in row["observations"]
                )
            )
            self.assertTrue(
                all(
                    obs["unit"] == "1"
                    for row in archived["input"]["molecules"]
                    for obs in row["observations"]
                )
            )
            report = client.get(path).json()["report"]
            scale = report["policies"][0]["strength_scale"]
            self.assertEqual(
                (scale["anchor_rank"], scale["anchor_lower"], scale["basis"]),
                (10, 9, "negative_log_molar"),
            )
            self.assertEqual(
                (scale["strong_boundary"], scale["medium_boundary"]), (8, 7)
            )
            bins = {
                item["label"]: item["molecules"]
                for item in report["distributions"][0]["bins"]
            }
            self.assertEqual(
                [bins[key] for key in ("strong", "medium", "weak", "missing")],
                [10, 1, 1, 1],
            )
            rows = client.get(path + "/rows?page_size=50").json()["items"]
            by_label = {row["label"]: row for row in rows}
            for label, band in (
                ("S10", "strong"),
                ("S11", "medium"),
                ("S12", "weak"),
                ("S13", "unclassified"),
            ):
                self.assertEqual(by_label[label]["activity_bands"][context], band)
            self.assertEqual(by_label["S10"]["values"][context], ["9"])
            self.assertEqual(
                client.get(path + "/rows?scope=strong&page_size=1").json()["total"], 10
            )
            client.get(path + "/rows?query=S12&page_size=1")
            self.assertEqual(
                client.get(path).json()["report"]["policies"][0]["strength_scale"],
                scale,
            )
            self.assertEqual(client.get(path + "/export?format=json").content, before)
            html = client.get(path + "/export?format=html").text
            self.assertIn("Strong &gt;8.0", html)
            self.assertIn("weak ≤7.0", html)
            self.assertIn(
                b"negative_log_molar", client.get(path + "/export?format=csv").content
            )
            # Old immutable studies stay readable, but do not acquire a rule they
            # never ran; a new analysis is required to use new scientific policy.
            legacy = {**archived["input"], "schema": 4}
            view = prepare_activity(
                legacy, StudyReport.model_validate(archived["report"])
            )
            self.assertEqual(view.policies[0].strength_scale.status, "unsupported")
            self.assertTrue(
                all(row.activity_bands[context] == "unclassified" for row in view.rows)
            )
            self.assertEqual(client.get(path + "/export?format=json").content, before)
