"""Catalogs retain every strict membership while detailed fragments load on demand."""

import unittest
from unittest.mock import patch

import test_sar_study_api as study_support
from test_sar_api import ROOT, nonce
from test_web_support import WebFixture


class SARCatalogTests(WebFixture, unittest.TestCase):
    dataset = study_support.SARStudyAPITests.dataset
    region = study_support.SARStudyAPITests.region
    start = study_support.SARStudyAPITests.start
    completed = study_support.SARStudyAPITests.completed

    def test_native_catalog_and_region_details_conserve_full_report_and_export(self):
        with self.client() as client:
            dataset = self.dataset(client, study_support.CSV)
            region = self.region(client, dataset)
            job, body = self.start(client, dataset, [region["id"]])
            self.completed(client, job)
            for automatic in (False, True):
                if automatic:
                    body.update(
                        request_id=nonce(), region_ids=[], discover_single_sites=True
                    )
                    reply = client.post(
                        ROOT + "/datasets/" + dataset["id"] + "/studies", json=body
                    )
                    self.assertEqual(reply.status_code, 202, reply.text)
                    job = self.completed(client, reply.json())
                path = ROOT + "/jobs/" + job["id"] + "/study"
                full = client.get(path).json()
                original = client.get(path + "/export?format=json").content
                with patch(
                    "patent_sar_extractor.web.sar.study_view_groups.CurrentStudyFragment.model_validate",
                    side_effect=AssertionError(
                        "Catalog must not build fragment chart DTOs"
                    ),
                ):
                    response = client.get(path + "/catalog")
                self.assertEqual(response.status_code, 200, response.text)
                catalog = response.json()
                self.assertEqual(catalog["detail"], "catalog")
                self.assertEqual(catalog["job"], full["job"])
                self.assertEqual(catalog["activity_basis"], full["activity_basis"])
                a, b = catalog["report"], full["report"]
                for key in b.keys() - {"regions"}:
                    self.assertEqual(a[key], b[key], key)
                self.assertEqual(len(a["regions"]), len(b["regions"]))
                for compact, detailed in zip(a["regions"], b["regions"], strict=True):
                    for key in detailed.keys() - {"fragments"}:
                        self.assertEqual(compact[key], detailed[key], key)
                    self.assertEqual(
                        len(compact["fragments"]), len(detailed["fragments"])
                    )
                    for short, long in zip(
                        compact["fragments"], detailed["fragments"], strict=True
                    ):
                        self.assertEqual(
                            set(short),
                            {
                                "id",
                                "molecule_ids",
                                "molecule_count",
                                "is_reference",
                                "representation",
                            },
                        )
                        self.assertEqual(short, {key: long[key] for key in short})
                    detail = client.get(path + "/regions/" + compact["region"]["id"])
                    self.assertEqual(detail.status_code, 200, detail.text)
                    self.assertEqual(detail.json()["region"], detailed)
                    self.assertEqual(
                        detail.json()["activity_basis"], catalog["activity_basis"]
                    )
                self.assertLess(len(response.content), len(client.get(path).content))
                self.assertEqual(
                    client.get(path + "/regions/" + "f" * 32).status_code, 404
                )
                self.assertEqual(
                    client.get(path + "/export?format=json").content, original
                )


if __name__ == "__main__":
    unittest.main()
