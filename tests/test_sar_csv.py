"""Focused CSV and identity regressions; public controlled graphs, no patent corpus."""

from __future__ import annotations

import unittest

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.csv_inputs import mapped_inputs
from patent_sar_extractor.web.sar.csv_reader import parse_csv, preview
from patent_sar_extractor.web.sar.models import CSVMapping


def mapping(**updates):
    return CSVMapping(
        token="a" * 32,
        title="Imported research",
        id_column="id",
        smiles_column="smiles",
        activity_columns=["IC50 (nM)"],
        request_id="b" * 32,
        **updates,
    )


class SARCSVTests(unittest.TestCase):
    def test_utf16_original_identifiers_and_missing_structure_are_preserved(self):
        data = "id,smiles,IC50 (nM)\n实施例 8A,CCO,12\nI-255,,A\n".encode("utf-16")
        info = preview(data, "结构.csv", "a" * 32)
        self.assertEqual(info.row_count, 2)
        records, metrics, count = mapped_inputs(data, mapping())
        self.assertEqual(count, 2)
        self.assertEqual([row.label for row in records], ["实施例 8A", "I-255"])
        self.assertTrue(records[0].eligible)
        self.assertFalse(records[1].eligible)
        self.assertEqual(records[1].observations[0].value, "A")
        self.assertEqual(metrics[0].unit, "nM")

    def test_long_csv_merges_same_identity_but_keeps_context_and_repeats(self):
        data = b"id,smiles,metric,value,unit,assay\n8A,CCO,IC50,10,nM,A\n8A,OCC,IC50,8,nM,A\n8B,CCN,IC50,2,nM,B\n"
        config = CSVMapping(
            token="a" * 32,
            title="Long",
            id_column="id",
            smiles_column="smiles",
            activity_columns=["value"],
            metric_column="metric",
            unit_column="unit",
            assay_column="assay",
            request_id="b" * 32,
        )
        records, metrics, count = mapped_inputs(data, config)
        self.assertEqual(count, 3)
        self.assertEqual(len(records), 2)
        self.assertEqual(len(records[0].observations), 2)
        self.assertEqual([obs.source_row for obs in records[0].observations], [1, 2])
        self.assertEqual(len(metrics), 2)
        self.assertNotEqual(metrics[0].id, metrics[1].id)

    def test_conflicting_identifier_graphs_are_not_guessed_or_overwritten(self):
        data = b"id,smiles,IC50 (nM)\nA,CCO,1\nA,CCN,2\n"
        records, _, count = mapped_inputs(data, mapping())
        self.assertEqual(count, 2)
        self.assertEqual(len(records), 2)
        self.assertTrue(
            all(
                not row.eligible and "identifier_conflict" in row.issues
                for row in records
            )
        )

    def test_no_activity_does_not_remove_the_structure(self):
        records, _, _ = mapped_inputs(b"id,smiles,IC50 (nM)\nS-1,CCO,\n", mapping())
        self.assertTrue(records[0].eligible)
        self.assertEqual(records[0].observations[0].value, "")

    def test_incompatible_duplicate_header_or_width_refuses_whole_import(self):
        for data in (
            b"id,id\n1,2\n",
            b"id,smiles\n1,CC,unexpected\n",
            b"id,smiles\n",
            b"id,smiles\n1,CC\x00O\n",
        ):
            with self.subTest(data=data), self.assertRaises(WebError):
                parse_csv(data)

    def test_mapping_cannot_alias_id_smiles_and_activity_roles(self):
        for updates in (
            {"smiles_column": "id"},
            {"activity_columns": ["id"]},
            {"activity_columns": ["missing"]},
        ):
            config = mapping().model_copy(update=updates)
            with self.assertRaises(WebError):
                mapped_inputs(b"id,smiles,IC50 (nM)\nX,CCO,1\n", config)

    def test_row_limit_is_error_not_silent_truncation(self):
        with self.assertRaises(WebError) as error:
            parse_csv(b"id,smiles\n" + b"X,CCO\n" * 25001)
        self.assertEqual(error.exception.code, "sar_row_limit")

    def test_literal_formula_text_not_decoded_in_generic_csv(self):
        records, _, _ = mapped_inputs(
            b"id,smiles,IC50 (nM)\n'=SUM(A1),CCO,'+++\n", mapping()
        )
        self.assertEqual(records[0].label, "'=SUM(A1)")
        self.assertEqual(records[0].observations[0].value, "'+++")


if __name__ == "__main__":
    unittest.main()
