"""Research evidence import boundaries and unchanged original identities."""

from __future__ import annotations

import unittest
import uuid

from patent_sar_extractor.core.sar.study_contexts import (
    context_catalog,
    context_identity,
)
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.csv_inputs import mapped_inputs
from patent_sar_extractor.web.sar.models import CSVMapping


class SARStudyInputTests(unittest.TestCase):
    def mapping(self, **extra):
        return CSVMapping(
            token="a" * 32,
            title="Imported evidence",
            id_column="id",
            smiles_column="smiles",
            activity_columns=["activity"],
            request_id=uuid.uuid4().hex,
            **extra,
        )

    def test_csv_properties_and_predictions_are_imported_not_model_verified(self):
        data = b"id,smiles,activity,LogS,risk,MW\nEx. 8A,CO,,,-0.0,32.0\n"
        records, metrics, count = mapped_inputs(
            data,
            self.mapping(
                property_columns={
                    "Solubility_AqSolDB": "LogS",
                    "molecular_weight": "MW",
                },
                prediction_columns={"hERG": "risk"},
            ),
        )
        row = records[0]
        self.assertEqual(row.label, "Ex. 8A")
        self.assertEqual(row.properties["molecular_weight"], 32.0)
        self.assertIsNone(row.properties["Solubility_AqSolDB"])
        self.assertEqual(row.prediction_origin, "imported")
        self.assertTrue(row.eligible)
        self.assertEqual(count, 1)
        self.assertEqual(len(metrics), 1)
        self.assertEqual(row.observations[0].value, "")

    def test_repeated_conflicting_research_values_remain_explicit_unknown(self):
        data = b"id,smiles,activity,MW,risk\n8B,CO,A,32,0.1\n8B,CO,B,33,0.2\n"
        records, _, count = mapped_inputs(
            data,
            self.mapping(
                property_columns={"molecular_weight": "MW"},
                prediction_columns={"hERG": "risk"},
            ),
        )
        self.assertEqual(count, 2)
        self.assertEqual(len(records), 1)
        row = records[0]
        self.assertEqual([item.value for item in row.observations], ["A", "B"])
        self.assertIsNone(row.properties["molecular_weight"])
        self.assertEqual(
            row.property_origins["molecular_weight"], "conflicting_imported"
        )
        self.assertIsNone(row.predictions["hERG"])
        self.assertEqual(row.prediction_origin, "conflicting_imported")
        self.assertTrue(row.eligible)

    def test_mapping_cannot_disguise_activity_as_safety_or_unknown_roles(self):
        data = b"id,smiles,activity,risk\n1,CO,A,0.2\n"
        for extra in [
            {"prediction_columns": {"hERG": "activity"}},
            {"prediction_columns": {"invented": "risk"}},
            {"property_columns": {"logP": "risk", "tpsa": "risk"}},
        ]:
            with self.subTest(extra=extra), self.assertRaises(WebError):
                mapped_inputs(data, self.mapping(**extra))

    def test_csv_source_page_is_original_evidence_not_the_input_row_number(self):
        data = b"id,smiles,activity,page\nEx. 1,CO,A,79\n"
        rows, _, _ = mapped_inputs(data, self.mapping(source_page_column="page"))
        self.assertEqual(rows[0].source_page, 79)
        self.assertEqual(rows[0].observations[0].source_page, 79)
        self.assertEqual(rows[0].observations[0].source_row, 1)
        with self.assertRaises(WebError):
            mapped_inputs(
                data.replace(b"79", b"0"), self.mapping(source_page_column="page")
            )

    def test_invalid_probability_finite_or_count_values_reject_complete_import(self):
        for raw, role in [
            ("1.2", "risk"),
            ("NaN", "risk"),
            ("-1", "mw"),
            ("1.5", "hbd"),
        ]:
            data = f"id,smiles,activity,x\n1,CO,A,{raw}\n".encode()
            extra = (
                {"prediction_columns": {"hERG": "x"}}
                if role == "risk"
                else {
                    "property_columns": {
                        "molecular_weight"
                        if role == "mw"
                        else "hydrogen_bond_donors": "x"
                    }
                }
            )
            with self.subTest(raw=raw), self.assertRaises(WebError):
                mapped_inputs(data, self.mapping(**extra))

    def test_exact_context_identity_never_normalizes_unknowns_or_cell_lines(self):
        original = {
            "metric_id": "m",
            "value": "A",
            "unit": "nM",
            "context": {"assay": "binding", "cell_line": None},
        }
        changed = {**original, "context": {"assay": "binding", "cell_line": "A"}}
        self.assertNotEqual(context_identity(original), context_identity(changed))
        self.assertNotEqual(
            context_identity(original), context_identity({**original, "unit": "nm"})
        )
        records = [
            {"id": "1", "observations": [original, original]},
            {"id": "2", "observations": [changed]},
        ]
        contexts = context_catalog(records, [{"id": "m", "name": "DC50"}])
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[0]["observation_count"], 2)
        self.assertEqual(contexts[0]["molecule_count"], 1)
