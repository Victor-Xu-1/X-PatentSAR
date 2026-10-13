"""Native study projections retain literal units and archived interpretation."""

import unittest
from dataclasses import replace

import test_sar_api as api
import test_sar_preview_records as record_support
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.preview_source import load_source
from patent_sar_extractor.web.sar.study_activity_view import prepare_activity
from patent_sar_extractor.web.sar.study_models import StudyReport
from patent_sar_extractor.web.sar.study_preview import verified_preview


class DeclaredUnitWorkflowTests(WebFixture, unittest.TestCase):
    completed = api.SARAPITests.completed
    region = api.SARAPITests.region
    prepare = record_support.SARPreviewRecordTests.prepare

    def test_native_supporting_pk_keeps_sources_and_archived_read_semantics(self):
        with self.client() as client:
            path, region, contexts, rows = self.prepare(client, declared_units=True)
            before = client.get(path + "/export?format=json").content
            names = {item["id"]: item["name"] for item in contexts}
            params = {"region_id": region["id"], "molecule_id": rows["P2"]["id"]}
            response = client.get(path + "/preview", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            records = response.json()["recorded_measurements"]
            reading = next(
                item
                for item in records
                if names[item["context_id"]] == "CL (mL/min/kg)"
            )
            self.assertEqual(reading["reference_values"], ["2 mL/min/kg"])
            self.assertEqual(reading["candidate_values"], ["5 mL/min/kg"])
            self.assertEqual(
                reading["difference"], {"status": "comparable", "value": 3.0}
            )
            matrix = client.get(
                path + "/matrix",
                params={**params, "reference_id": region["molecule_id"]},
            )
            self.assertEqual(matrix.status_code, 200, matrix.text)
            self.assertEqual(
                matrix.json()["previews"][0]["recorded_measurements"], records
            )
            queue = client.app.state.sar_queue
            source = load_source(queue, path.split("/")[-2])
            legacy = replace(source, packet={**source.packet, "schema": 6})
            old = verified_preview(queue, legacy, region["id"], rows["P2"]["id"]).data
            reading = next(
                item
                for item in old.recorded_measurements
                if names[item.context_id] == "CL (mL/min/kg)"
            )
            self.assertEqual(reading.difference.status, "indeterminate")
            self.assertIsNone(reading.difference.value)
            self.assertEqual(client.get(path + "/export?format=json").content, before)

    def test_selected_declared_units_flow_through_pairs_current_rows_and_numeric_sort(
        self,
    ):
        with self.client() as client:
            path, region, contexts, rows = self.prepare(
                client, declared_units=True, metric="CL (mL/min/kg)"
            )
            archive = client.get(path + "/export?format=json")
            self.assertEqual(archive.status_code, 200)
            self.assertEqual(archive.json()["input"]["schema"], 7)
            context = next(
                item for item in contexts if item["name"] == "CL (mL/min/kg)"
            )
            report = client.get(path).json()["report"]
            self.assertTrue(
                all(
                    row["activity_status"][context["id"]] in {"scalar", "interval"}
                    for row in report["rows"]
                )
            )
            self.assertEqual(
                report["policies"][0]["strength_scale"]["status"], "unsupported"
            )
            self.assertTrue(all(not row["strong"] for row in report["rows"]))
            response = client.get(
                path + "/preview",
                params={"region_id": region["id"], "molecule_id": rows["P2"]["id"]},
            )
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()["measurements"][0]
            self.assertEqual(value["comparison"], "worse")
            self.assertEqual(value["raw_difference"], 3.0)
            ordered = client.get(
                path + "/rows",
                params={"sort_by": "context:" + context["id"], "sort_direction": "asc"},
            ).json()["items"]
            self.assertEqual(
                [row["label"] for row in ordered], ["P4", "P1", "P2", "P3"]
            )
            queue = client.app.state.sar_queue
            source = load_source(queue, path.split("/")[-2])
            legacy = replace(source, packet={**source.packet, "schema": 6})
            old = verified_preview(queue, legacy, region["id"], rows["P2"]["id"]).data
            self.assertEqual(old.measurements[0].comparison, "indeterminate")
            self.assertIsNone(old.measurements[0].raw_difference)
            legacy_activity = prepare_activity(
                legacy.packet, StudyReport.model_validate(archive.json()["report"])
            )
            self.assertFalse(legacy_activity.declared_units)
            self.assertTrue(
                all(
                    state["status"] == "indeterminate"
                    for state in legacy_activity.assessments[context["id"]].values()
                )
            )
            self.assertEqual(
                client.get(path + "/export?format=json").content, archive.content
            )
            self.assertEqual(rows["P1"]["observations"][1]["value"], "2 mL/min/kg")


if __name__ == "__main__":
    unittest.main()
