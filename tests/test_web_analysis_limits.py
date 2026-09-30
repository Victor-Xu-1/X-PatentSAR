"""Physical-limit warnings using values from the real 2.0.1 aspirin preflight.

The recorded numbers below are real local model outputs, not measured chemistry.
PPBR >100 and log-VDss are explicit boundary cases, not claimed real predictions.
"""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from patent_sar_extractor.web.analysis_models import ADMETResponse
from patent_sar_extractor.web.analysis_results import admet_response
from patent_sar_extractor.web.analysis_runtime import Endpoint, ModelBundle
from patent_sar_extractor.workers.analysis_protocol import ADMET_BUNDLE_SHA256


class PhysicalLimitsTests(unittest.TestCase):
    def fixture(self):
        endpoints = {
            "Half_Life_Obach": Endpoint(
                "Half_Life_Obach", "Half Life", "hr", "prediction", False, 0, None
            ),
            "PPBR_AZ": Endpoint(
                "PPBR_AZ",
                "Plasma Protein Binding Rate",
                "%",
                "prediction",
                False,
                0,
                100,
            ),
            "VDss_Lombardo": Endpoint(
                "VDss_Lombardo",
                "Volume of Distribution at Steady State",
                "L/kg",
                "prediction",
                False,
                0,
                None,
            ),
            "Solubility_AqSolDB": Endpoint(
                "Solubility_AqSolDB",
                "Aqueous Solubility",
                "log(mol/L)",
                "prediction",
                False,
            ),
            "Caco2_Wang": Endpoint(
                "Caco2_Wang",
                "Cell Effective Permeability",
                "log(10^-6 cm/s)",
                "prediction",
                False,
            ),
        }
        numbers = {
            "Half_Life_Obach": -19.730005264282227,
            "PPBR_AZ": 63.29743194580078,
            "VDss_Lombardo": -2.7047996520996094,
            "Solubility_AqSolDB": -1.6242990493774414,
            "Caco2_Wang": -4.563969612121582,
        }
        properties = [
            {
                "key": key,
                "label": item.label,
                "unit": item.unit,
                "kind": item.kind,
                "value": numbers[key],
            }
            for key, item in endpoints.items()
        ]
        payload = {
            "engine": {
                "name": "ADMET-AI",
                "version": "2.0.1",
                "model_sha256": ADMET_BUNDLE_SHA256,
            },
            "generated_at": "2026-09-30T14:33:11+00:00",
            "review_only": True,
            "predictions": [
                {"smiles": "CC(=O)Oc1ccccc1C(=O)O", "properties": properties}
            ],
            "warnings": [
                "Research estimates, not experiments; applicability has not been independently validated."
            ],
        }
        return payload, ModelBundle(
            Path("unused-model-fixture"), ADMET_BUNDLE_SHA256, endpoints
        )

    def test_real_negative_hour_and_declared_l_per_kg_warn_without_transform(self):
        payload, bundle = self.fixture()
        original = copy.deepcopy(payload["predictions"])
        result = admet_response(payload, [payload["predictions"][0]["smiles"]], bundle)
        self.assertEqual([p.model_dump() for p in result.predictions], original)
        self.assertTrue(result.review_only)
        self.assertTrue(
            any(
                "Half_Life_Obach" in warning and "不得作为有效参数" in warning
                for warning in result.warnings
            )
        )
        self.assertTrue(
            any(
                "VDss_Lombardo" in warning and "不猜测逆变换" in warning
                for warning in result.warnings
            )
        )
        self.assertFalse(
            any(
                "Solubility_AqSolDB" in warning or "Caco2_Wang" in warning
                for warning in result.warnings
            )
        )
        self.assertIn("applicability", result.warnings[0])
        cached = admet_response(
            result.model_dump(), [result.predictions[0].smiles], bundle
        )
        self.assertEqual(cached.warnings, result.warnings)

    def test_percent_above_100_warns_and_keeps_the_raw_prediction(self):
        payload, bundle = self.fixture()
        ppbr = next(
            p for p in payload["predictions"][0]["properties"] if p["key"] == "PPBR_AZ"
        )
        ppbr["value"] = 101.25
        result = admet_response(payload, [payload["predictions"][0]["smiles"]], bundle)
        value = next(
            p.value for p in result.predictions[0].properties if p.key == "PPBR_AZ"
        )
        self.assertEqual(value, 101.25)
        self.assertTrue(
            any(
                "PPBR_AZ" in warning and "不做 clamp" in warning
                for warning in result.warnings
            )
        )

    def test_log_scale_negative_values_and_physical_boundaries_are_not_flagged(self):
        payload, bundle = self.fixture()
        for item in payload["predictions"][0]["properties"]:
            if item["key"] == "Half_Life_Obach":
                item["value"] = 0.0
            if item["key"] == "PPBR_AZ":
                item["value"] = 100.0
            if item["key"] == "VDss_Lombardo":
                item["unit"] = "log(L/kg)"
        bundle.endpoints["VDss_Lombardo"] = Endpoint(
            "VDss_Lombardo",
            "Volume of Distribution at Steady State",
            "log(L/kg)",
            "prediction",
            False,
            0,
            None,
        )
        result = admet_response(payload, [payload["predictions"][0]["smiles"]], bundle)
        self.assertEqual(len(result.warnings), 1)
        self.assertIsInstance(result, ADMETResponse)

    def test_full_50_molecule_batch_has_bounded_complete_physical_warnings(self):
        payload, bundle = self.fixture()
        one = payload["predictions"][0]
        payload["predictions"] = [copy.deepcopy(one) for _ in range(50)]
        for index, prediction in enumerate(payload["predictions"]):
            prediction["properties"][0]["value"] = -1.0 - index
        result = admet_response(payload, [one["smiles"]] * 50, bundle)
        self.assertEqual(len(result.predictions), 50)
        self.assertEqual(len(result.warnings), 3)
        half_life = next(w for w in result.warnings if "Half_Life_Obach" in w)
        self.assertIn("第1项=-1", half_life)
        self.assertIn("第50项=-50", half_life)
