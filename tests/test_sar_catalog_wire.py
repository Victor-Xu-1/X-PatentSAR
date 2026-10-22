"""Pure wire conservation and size, no private patent/model computation."""

import copy
import json
import unittest

import test_sar_study_api as support
from pydantic import ValidationError
from test_sar_api import ROOT
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.study_catalog_models import CatalogFragment
from patent_sar_extractor.web.sar.study_catalog_wire import PooledFragment


def expanded(packet):
    value = copy.deepcopy(packet)
    value["detail"] = "catalog"
    value.pop("wire_version")
    fragments = value.pop("fragment_pool")
    members = value.pop("molecule_id_pool")
    for fragment in fragments:
        fragment["molecule_ids"] = members[fragment["molecule_ids"]]
    for region in value["report"]["regions"]:
        region["fragments"] = [fragments[ref] for ref in region["fragments"]]
    return value


class CatalogWireModelsTests(unittest.TestCase):
    def test_pooled_fragment_inherits_every_field_without_a_second_allowlist(self):
        self.assertEqual(
            set(CatalogFragment.model_fields), set(PooledFragment.model_fields)
        )
        for invalid in (-1, 1.2, True, "0", [], None):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                PooledFragment(
                    id="same",
                    molecule_ids=invalid,
                    molecule_count=1,
                    is_reference=False,
                )


class CatalogWireConservationTests(WebFixture, unittest.TestCase):
    dataset = support.SARStudyAPITests.dataset
    region = support.SARStudyAPITests.region
    start = support.SARStudyAPITests.start
    completed = support.SARStudyAPITests.completed

    def fixture(self):
        from patent_sar_extractor.web.sar.study_catalog_models import StudyCatalog

        with self.client() as client:
            dataset = self.dataset(client, support.CSV)
            region = self.region(client, dataset)
            job, _ = self.start(client, dataset, [region["id"]])
            self.completed(client, job)
            response = client.get(ROOT + "/jobs/" + job["id"] + "/study/catalog")
            self.assertEqual(response.status_code, 200, response.text)
            return StudyCatalog.model_validate(response.json())

    def test_complete_entry_identity_and_order_survive_all_pool_uses(self):
        # Use a normal service catalog as the typed metadata/receipt source.
        from patent_sar_extractor.web.sar.study_catalog_wire import pooled_catalog

        catalog = self.fixture()
        original = catalog.report.regions[0].fragments[0]
        variants = [
            original.model_copy(update={"molecule_ids": ["A", "B"]}),
            original.model_copy(update={"molecule_ids": ["B", "A"]}),
            original.model_copy(update={"molecule_ids": ["A", "C"]}),
            original.model_copy(update={"molecule_count": 99}),
            original.model_copy(update={"is_reference": not original.is_reference}),
            original.model_copy(update={"representation": "aromatic_graph"}),
        ]
        catalog.report.regions = [
            catalog.report.regions[0].model_copy(
                update={
                    "region": catalog.report.regions[0].region.model_copy(
                        update={"id": f"{n:032x}"}
                    ),
                    "fragments": variants + [original, original],
                }
            )
            for n in range(101)
        ]
        before = catalog.model_dump(mode="json")
        packed = pooled_catalog(catalog)
        self.assertEqual(packed.detail, "catalog-pooled")
        wire = packed.model_dump(mode="json")
        self.assertEqual(expanded(wire), before)
        self.assertEqual(catalog.model_dump(mode="json"), before)
        self.assertEqual(len(wire["fragment_pool"]), len(variants) + 1)
        self.assertEqual(len(wire["molecule_id_pool"]), 4)
        self.assertLess(
            len(packed.model_dump_json()), len(catalog.model_dump_json()) // 2
        )
        self.assertEqual(
            len(json.dumps(expanded(wire), ensure_ascii=False)),
            len(json.dumps(before, ensure_ascii=False)),
        )

    def test_empty_and_small_unique_catalogs_keep_the_legacy_wire(self):
        from patent_sar_extractor.web.sar.study_catalog_wire import pooled_catalog

        catalog = self.fixture()
        self.assertIs(pooled_catalog(catalog), catalog)
        catalog.report.regions = []
        self.assertIs(pooled_catalog(catalog), catalog)
