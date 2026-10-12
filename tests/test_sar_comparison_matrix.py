"""One bounded, source-bound multi-candidate view of published strict comparisons."""

import unittest
from unittest.mock import patch

import test_sar_preview_records as support
from test_web_support import WebFixture


class SARComparisonMatrixTests(WebFixture, unittest.TestCase):
    prepare = support.SARPreviewRecordTests.prepare
    completed = support.SARPreviewRecordTests.completed
    region = support.SARPreviewRecordTests.region

    def query(self, region, rows, labels=("P2", "P3")):
        return [
            ("reference_id", rows["P1"]["id"]),
            *[("region_id", region["id"]) for _ in labels],
            *[("molecule_id", rows[label]["id"]) for label in labels],
        ]

    def test_all_candidates_keep_reference_raw_pk_repeats_and_source_archives(self):
        with self.client() as client:
            path, region, contexts, rows = self.prepare(client, repeated=True)
            original = client.get(path + "/export?format=json").content
            response = client.get(path + "/matrix", params=self.query(region, rows))
            self.assertEqual(response.status_code, 200, response.text)
            matrix = response.json()
            self.assertEqual(matrix["reference_drawing"]["id"], rows["P1"]["id"])
            self.assertEqual(len(matrix["previews"]), 2)
            self.assertEqual(
                [item["candidate"]["label"] for item in matrix["previews"]],
                ["P2", "P3"],
            )
            names = {item["id"]: item["name"] for item in contexts}
            for item in matrix["previews"]:
                self.assertEqual(item["reference"]["label"], "P1")
                self.assertEqual(item["pair"]["match_status"], "matched")
                self.assertEqual(item["measurements"][0]["reference_values"], ["10"])
                self.assertEqual(item["drawings"]["reference"]["id"], rows["P1"]["id"])
                self.assertIn("<svg", item["drawings"]["candidate"]["svg"])
                raw = {
                    names[value["context_id"]]: value
                    for value in item["recorded_measurements"]
                }
                self.assertEqual(raw["CL (mL/min/kg)"]["reference_values"], ["2"])
                self.assertNotIn("raw_difference", raw["CL (mL/min/kg)"])
                self.assertNotIn("comparison", raw["CL (mL/min/kg)"])
                self.assertEqual(
                    set(item["property_statuses"]), set(item["property_differences"])
                )
                for key, status in item["property_statuses"].items():
                    self.assertEqual(
                        status == "comparable",
                        item["property_differences"][key] is not None,
                    )
            final = matrix["previews"][1]
            raw = {
                names[value["context_id"]]: value
                for value in final["recorded_measurements"]
            }
            self.assertEqual(raw["CL (mL/min/kg)"]["candidate_values"], ["<6", ">9"])
            self.assertEqual(raw["Ymin"]["candidate_values"], ["", ""])
            self.assertEqual(client.get(path + "/export?format=json").content, original)

    def test_invalid_duplicate_mixed_reference_or_unproved_selection_is_not_partial_success(
        self,
    ):
        with self.client() as client:
            path, region, _contexts, rows = self.prepare(client)
            good = self.query(region, rows)
            for query in (
                [],
                [("reference_id", rows["P1"]["id"])],
                [("reference_id", rows["P2"]["id"]), *good[1:]],
                self.query(region, rows, ("P2", "P2")),
                self.query(region, rows, ("P2", "P4")),
                self.query(region, rows, ("P2",) * 7),
                [*good, ("region_id", region["id"])],
                [("reference_id", "x" * 201), *good[1:]],
            ):
                response = client.get(path + "/matrix", params=query)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn("previews", response.json())

    def test_matrix_checks_one_immutable_input_and_full_proof_for_every_candidate(self):
        from patent_sar_extractor.web.sar import preview_source, study_preview

        with self.client() as client:
            path, region, _contexts, rows = self.prepare(client)
            with (
                patch.object(
                    preview_source, "digest", wraps=preview_source.digest
                ) as checked,
                patch.object(
                    study_preview,
                    "compile_reference",
                    wraps=study_preview.compile_reference,
                ) as compiled,
            ):
                response = client.get(path + "/matrix", params=self.query(region, rows))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(checked.call_count, 1)
            self.assertEqual(compiled.call_count, 1)
            self.assertEqual(len(response.json()["previews"]), 2)

    def test_complete_wire_limit_refuses_without_truncating_candidates(self):
        with self.client() as client:
            path, region, _contexts, rows = self.prepare(client)
            with patch(
                "patent_sar_extractor.web.sar.matrix_models.StudyMatrix.model_dump_json",
                return_value="x" * (8 * 1024 * 1024 + 1),
            ):
                response = client.get(path + "/matrix", params=self.query(region, rows))
            self.assertEqual(response.status_code, 413)
            self.assertNotIn("previews", response.json())
