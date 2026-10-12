"""Origin-aware property differences are read views, not inferred evidence."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_sar_preview_records as support
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.preview_properties import property_comparisons


class SARPropertyPreviewTests(unittest.TestCase):
    def rows(self, left=10.0, right=11.0, first=None, second=None):
        return (
            SimpleNamespace(
                properties={"molecular_weight": left}, property_origins=first or {}
            ),
            SimpleNamespace(
                properties={"molecular_weight": right}, property_origins=second or {}
            ),
        )

    def test_unknown_absent_blank_and_unprovided_origins_never_become_a_delta(self):
        for origin in (
            None,
            "",
            " ",
            "unknown",
            "not_provided",
            "manual_null",
            "future_method",
        ):
            data = {} if origin is None else {"molecular_weight": origin}
            rows = self.rows(first=data, second=data)
            result = property_comparisons(*rows)
            self.assertIsNone(result.differences["molecular_weight"])
            self.assertEqual(result.statuses["molecular_weight"], "origin_unknown")
            self.assertEqual(rows[0].properties["molecular_weight"], 10)
            self.assertEqual(rows[1].properties["molecular_weight"], 11)

    def test_known_equal_origins_allow_arithmetic_but_never_improvement_claims(self):
        for origin in (
            "computed_rdkit",
            "imported",
            "manual",
            "verified_project_descriptor",
            "verified_project_model",
        ):
            data = {"molecular_weight": origin}
            result = property_comparisons(*self.rows(first=data, second=data))
            self.assertEqual(result.differences["molecular_weight"], 1)
            self.assertEqual(result.statuses["molecular_weight"], "comparable")

    def test_mixed_known_origins_missing_values_and_float_overflow_are_explicit(self):
        first, second = {"molecular_weight": "manual"}, {"molecular_weight": "imported"}
        result = property_comparisons(*self.rows(first=first, second=second))
        self.assertEqual(result.statuses["molecular_weight"], "origin_mismatch")
        self.assertIsNone(result.differences["molecular_weight"])
        result = property_comparisons(*self.rows(left=None, first=first, second=first))
        self.assertEqual(result.statuses["molecular_weight"], "missing")
        result = property_comparisons(
            *self.rows(left=-1e308, right=1e308, first=first, second=first)
        )
        self.assertEqual(result.statuses["molecular_weight"], "not_representable")
        self.assertIsNone(result.differences["molecular_weight"])


class SARPropertyPreviewAPITests(WebFixture, unittest.TestCase):
    prepare = support.SARPreviewRecordTests.prepare
    completed = support.SARPreviewRecordTests.completed
    region = support.SARPreviewRecordTests.region

    def test_pair_and_matrix_share_the_unknown_origin_guard_without_changing_archive(
        self,
    ):
        from patent_sar_extractor.web.sar.preview_source import load_source

        def legacy_source(queue, identifier):
            source = load_source(queue, identifier)
            # Controlled in-memory legacy metadata only. The immutable source,
            # report file, full chemistry proof and published pairs stay real.
            rows = [row.model_copy(deep=True) for row in source.rows.values()]
            for row in rows:
                row.property_origins.pop("molecular_weight", None)
            source.rows = {row.molecule_id: row for row in rows}
            return source

        with self.client() as client:
            path, region, _contexts, rows = self.prepare(client)
            original = client.get(path + "/export?format=json").content
            with (
                patch(
                    "patent_sar_extractor.web.sar.study_preview.load_source",
                    legacy_source,
                ),
                patch(
                    "patent_sar_extractor.web.sar.study_matrix.load_source",
                    legacy_source,
                ),
            ):
                pair = client.get(
                    path + "/preview",
                    params={
                        "region_id": region["id"],
                        "molecule_id": rows["P2"]["id"],
                    },
                )
                matrix = client.get(
                    path + "/matrix",
                    params={
                        "reference_id": rows["P1"]["id"],
                        "region_id": region["id"],
                        "molecule_id": rows["P2"]["id"],
                    },
                )
            self.assertEqual(pair.status_code, 200, pair.text)
            self.assertEqual(matrix.status_code, 200, matrix.text)
            for data in (pair.json(), matrix.json()["previews"][0]):
                self.assertIsNone(data["property_differences"]["molecular_weight"])
                self.assertEqual(
                    data["property_statuses"]["molecular_weight"], "origin_unknown"
                )
                self.assertIsNotNone(
                    data["reference"]["properties"]["molecular_weight"]
                )
                self.assertIsNotNone(
                    data["candidate"]["properties"]["molecular_weight"]
                )
            self.assertEqual(client.get(path + "/export?format=json").content, original)
