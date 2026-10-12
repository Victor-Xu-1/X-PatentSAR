"""Generic source-header matching; numbers alone are not activity endpoints."""

import unittest

from test_sar_api import ROOT, nonce
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.csv_reader import preview


class SARCSVDefaultTests(unittest.TestCase):
    def test_wide_defaults_separate_activity_metadata_properties_and_declared_predictions(
        self,
    ):
        data = b"Compound ID,SMILES,IC50 (nM),Ymin,MW,LogP,TPSA,HBD,HBA,LogS,Assay,Cell Line,Duration,Target,PDF Page,predicted hERG,Year,hERG\nI-1,CO,1,20,32,0.4,20,1,2,-1,binding,C,1h,T,7,0.1,2026,0.2\n"
        result = preview(data, "generic.csv", "a" * 32).model_dump()
        self.assertEqual(result["suggested_id"], "Compound ID")
        self.assertEqual(result["suggested_smiles"], "SMILES")
        self.assertEqual(result["suggested_activities"], ["IC50 (nM)", "Ymin"])
        defaults = result.get("mapping_defaults", {})
        self.assertEqual(
            defaults.get("columns"),
            {
                "assay_column": "Assay",
                "cell_line_column": "Cell Line",
                "duration_column": "Duration",
                "target_column": "Target",
                "source_page_column": "PDF Page",
            },
        )
        self.assertEqual(
            defaults.get("property_columns"),
            {
                "molecular_weight": "MW",
                "logP": "LogP",
                "tpsa": "TPSA",
                "hydrogen_bond_donors": "HBD",
                "hydrogen_bond_acceptors": "HBA",
                "Solubility_AqSolDB": "LogS",
            },
        )
        self.assertEqual(defaults.get("prediction_columns"), {"hERG": "predicted hERG"})
        self.assertEqual(result["samples"][0]["Year"], "2026")

    def test_long_aliases_preserve_headers_labels_units_and_every_row(self):
        data = "编号,Isomeric SMILES,Endpoint,Activity Value,单位,实验方法,细胞系,处理时长\n008B,CO,DC50,<1,nM,binding,C,1h\n009,CCO,DC50,,nM,binding,C,1h\n".encode()
        result = preview(data, "原文.csv", "a" * 32).model_dump()
        self.assertEqual(result["suggested_id"], "编号")
        self.assertEqual(result["suggested_smiles"], "Isomeric SMILES")
        self.assertEqual(result["suggested_activities"], ["Activity Value"])
        self.assertEqual(
            result.get("mapping_defaults", {}).get("columns", {}).get("metric_column"),
            "Endpoint",
        )
        self.assertEqual(
            result.get("mapping_defaults", {}).get("columns", {}).get("unit_column"),
            "单位",
        )
        self.assertEqual(result["samples"][0]["编号"], "008B")
        self.assertEqual(result["samples"][0]["Activity Value"], "<1")
        self.assertEqual(result["row_count"], 2)

    def test_normalized_collisions_unknown_numbers_and_incompatible_property_units_are_not_guessed(
        self,
    ):
        data = b"id,SMILES,smiles,IC50 (nM),MW,molecular_weight,LogP (nM),Mystery,Year\n1,CO,CCO,1,32,33,1,0.1,2026\n"
        result = preview(data, "ambiguous.csv", "a" * 32).model_dump()
        self.assertIsNone(result["suggested_smiles"])
        self.assertEqual(result["suggested_activities"], ["IC50 (nM)"])
        self.assertEqual(result.get("mapping_defaults", {}).get("property_columns"), {})
        self.assertIn(
            "smiles_column",
            result.get("mapping_defaults", {}).get("ambiguous_roles", []),
        )
        self.assertIn(
            "molecular_weight",
            result.get("mapping_defaults", {}).get("ambiguous_roles", []),
        )

    def test_source_display_identifier_wins_over_internal_export_id(self):
        data = b"compound_id,identifier_label,smiles,metric,value\nsource:hash,008B,CO,EC50,<1\n"
        result = preview(data, "export.csv", "a" * 32).model_dump()
        self.assertEqual(result["suggested_id"], "identifier_label")
        self.assertEqual(result["suggested_activities"], ["value"])

    def test_more_than_64_endpoints_requires_explicit_selection_not_a_silent_prefix(
        self,
    ):
        headers = ["id", "smiles", *[f"Assay {index} IC50 (nM)" for index in range(65)]]
        data = (
            ",".join(headers) + "\n" + ",".join(["1", "CO", *["1"] * 65]) + "\n"
        ).encode()
        result = preview(data, "large.csv", "a" * 32).model_dump()
        self.assertEqual(len(result["headers"]), 67)
        self.assertEqual(result["suggested_activities"], [])
        self.assertIn("activity_columns", result["mapping_defaults"]["ambiguous_roles"])


class SARCSVDefaultAPITests(WebFixture, unittest.TestCase):
    def test_native_one_submit_import_preserves_values_conditions_and_research_roles(
        self,
    ):
        data = b"Compound ID,SMILES,IC50 (nM),MW,Assay,Cell Line,Duration,PDF Page,predicted hERG\nI-1,CO,1,32,binding,C,1h,7,0.1\nI-2,CCO,,46,binding,C,1h,8,0.2\nIntermediate 1,CO,0.001,32,binding,C,1h,7,0.1\n"
        with self.client() as client:
            reply = client.post(
                ROOT + "/csv/preview?filename=known.csv",
                content=data,
                headers={"Content-Type": "text/csv"},
            )
            self.assertEqual(reply.status_code, 200, reply.text)
            result = reply.json()
            hints = result["mapping_defaults"]
            body = {
                "token": result["token"],
                "request_id": nonce(),
                "title": "Known columns",
                "id_column": result["suggested_id"],
                "smiles_column": result["suggested_smiles"],
                "activity_columns": result["suggested_activities"],
                **hints["columns"],
                "property_columns": hints["property_columns"],
                "prediction_columns": hints["prediction_columns"],
            }
            created = client.post(ROOT + "/datasets/csv", json=body)
            self.assertEqual(created.status_code, 201, created.text)
            dataset = created.json()
            self.assertEqual(dataset["input_row_count"], 3)
            self.assertEqual(dataset["row_count"], 2)
            self.assertEqual(
                [metric["name"] for metric in dataset["metrics"]], ["IC50 (nM)"]
            )
            path = ROOT + "/datasets/" + dataset["id"]
            rows = client.get(path + "/molecules").json()["items"]
            self.assertEqual([row["label"] for row in rows], ["I-1", "I-2"])
            self.assertEqual(rows[0]["observations"][0]["context"]["cell_line"], "C")
            self.assertEqual(rows[0]["observations"][0]["source_page"], 7)
            self.assertEqual(rows[0]["observations"][0]["value"], "1")
            self.assertEqual(rows[1]["observations"][0]["value"], "")
            self.assertEqual(rows[1]["properties"]["molecular_weight"], 46)
            self.assertEqual(rows[0]["predictions"]["hERG"], 0.1)
            self.assertEqual(rows[0]["prediction_origin"], "imported")
            self.assertEqual(
                client.post(ROOT + "/datasets/csv", json=body).json()["id"],
                dataset["id"],
            )
            self.assertEqual(client.get(path + "/jobs").json()["items"], [])
