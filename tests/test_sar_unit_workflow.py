"""Native source-preserving unit interpretation across SAR charts, filters and sort."""

from __future__ import annotations

import unittest

import test_sar_api as support
import test_sar_potency_bands as potency
import test_sar_study_analysis as study
from test_sar_statistics import observation
from test_web_support import WebFixture

from patent_sar_extractor.core.sar.study_statistics import assess
from patent_sar_extractor.web.sar.input_records import analysis_molecules
from patent_sar_extractor.web.sar.models import Molecule


class SARUnitWorkflowTests(WebFixture, unittest.TestCase):
    run_study = potency.SARPotencyTests.run_study
    completed = support.SARAPITests.completed

    def test_explicit_cell_units_work_without_header_units_and_do_not_modify_dataset(
        self,
    ):
        raw = ["0.1 nM"] * 9 + ["0.001 µM", "10 nM", "0.1 uM", ""]
        with self.client() as client:
            path, context = self.run_study(client, raw, metric="IC50")
            archive = client.get(path + "/export?format=json").json()
            dataset = archive["input"]["dataset"]["id"]
            stored = client.get(
                support.ROOT + "/datasets/" + dataset + "/molecules"
            ).json()["items"]
            self.assertTrue(
                all(row["observations"][0]["unit"] is None for row in stored)
            )
            source_by_label = {
                row["label"]: row["observations"][0]["value"] for row in stored
            }
            self.assertEqual(
                source_by_label, {f"S{i + 1}": value for i, value in enumerate(raw)}
            )
            self.assertEqual(
                archive["input"]["molecules"][0]["observations"][0]["unit"], "nM"
            )
            report = client.get(path).json()["report"]
            selected = next(
                item for item in report["contexts"] if item["id"] == context
            )
            self.assertEqual(selected["unit"], "nM")
            self.assertEqual(
                report["policies"][0]["strength_scale"]["strong_boundary"], 10
            )
            self.assertEqual(
                client.get(path + "/rows?scope=strong").json()["total"], 10
            )

    def test_analysis_preparation_never_borrows_units_from_neighbouring_records(self):
        for source_kind in ("imported", "patent", "manual"):
            with self.subTest(source_kind=source_kind):
                records = []
                for index, raw in enumerate(("10 nM", "0.002 µM", "10", "80%")):
                    item = study.molecule(str(index), "CO", raw)
                    item["observations"][0].update(unit=None, source_kind=source_kind)
                    records.append(Molecule.model_validate(item))
                original = [record.model_dump() for record in records]
                prepared = analysis_molecules(records)
                self.assertEqual(
                    [row.observations[0].unit for row in prepared],
                    ["nM", "nM", None, "%"],
                )
                self.assertEqual([record.model_dump() for record in records], original)

    def test_whole_population_has_one_unit_scale_and_keeps_original_readings(self):
        raw = ["0.1 nM"] * 9 + ["0.001 µM", "10 nM", "0.1 uM", ""]
        with self.client() as client:
            path, context = self.run_study(client, raw)
            original = client.get(path + "/export?format=json")
            self.assertEqual(original.status_code, 200, original.text)
            report = client.get(path).json()["report"]
            scale = report["policies"][0]["strength_scale"]
            self.assertEqual(
                (
                    scale["status"],
                    scale["anchor_rank"],
                    scale["population"],
                    scale["strong_boundary"],
                    scale["medium_boundary"],
                ),
                ("ready", 10, 12, 10, 100),
            )
            bins = {
                item["label"]: item["molecules"]
                for item in report["distributions"][0]["bins"]
            }
            self.assertEqual(
                (bins["strong"], bins["medium"], bins["weak"], bins["missing"]),
                (10, 1, 1, 1),
            )
            rows = client.get(
                path + "/rows",
                params={"sort_by": "context:" + context, "sort_direction": "asc"},
            ).json()["items"]
            self.assertEqual(
                [row["label"] for row in rows], [f"S{i}" for i in range(1, 14)]
            )
            self.assertEqual([row["values"][context][0] for row in rows], raw)
            descending = client.get(
                path + "/rows",
                params={"sort_by": "context:" + context, "sort_direction": "desc"},
            ).json()["items"]
            self.assertEqual(
                [row["label"] for row in descending[:3]], ["S12", "S11", "S10"]
            )
            self.assertEqual(descending[-1]["label"], "S13")
            self.assertEqual(
                client.get(path + "/rows?scope=strong&page_size=2").json()["total"], 10
            )
            self.assertEqual(
                client.get(path + "/export?format=json").content, original.content
            )
            archive = original.json()
            self.assertEqual(archive["input"]["schema"], 6)
            self.assertEqual(
                [
                    row["observations"][0]["value"]
                    for row in archive["input"]["molecules"]
                ],
                raw,
            )
            self.assertIn("0.001 µM", client.get(path + "/export?format=csv").text)

    def test_equivalent_repeats_are_not_conflicts_or_extra_molecules(self):
        records = [observation("1 nM"), observation("0.001 µM")]
        policy = {
            "direction": "lower",
            "grade_order": [],
            "strength_method": "unclassified",
        }
        state = assess(records, policy, False)
        self.assertEqual(state["status"], "scalar")
        self.assertIn("repeated_measurements", state["reasons"])
        self.assertEqual(state["values"], ["1 nM", "0.001 µM"])
        old = assess(records, policy, False, inline_units=False)
        self.assertEqual(old["status"], "indeterminate")


if __name__ == "__main__":
    unittest.main()
