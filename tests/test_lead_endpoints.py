"""Additional model evidence preserves the original six-property contract."""

import unittest

from pydantic import ValidationError
from test_prediction_fields import controlled_prediction
from test_prediction_support import controlled_summary

from patent_sar_extractor.web.analysis_models import Property
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.lead_endpoints import selected_endpoints
from patent_sar_extractor.web.prediction_models import PredictionSummary


class LeadEndpointTests(unittest.TestCase):
    def test_only_reviewed_probability_metadata_enters_score_and_raw_regressions_do_not(
        self,
    ):
        prediction = controlled_prediction()
        prediction.properties.extend(
            [
                Property(
                    key="hERG",
                    label="hERG",
                    value=0.2,
                    unit="probability [0,1]",
                    kind="prediction",
                ),
                Property(
                    key="VDss_Lombardo",
                    label="VDss",
                    value=-0.5,
                    unit="L/kg",
                    kind="prediction",
                ),
            ]
        )
        self.assertEqual(selected_endpoints(prediction), {"hERG": 0.2})
        self.assertEqual(prediction.properties[-1].value, -0.5)

    def test_legacy_six_metric_packet_is_still_readable_but_does_not_invent_admet(self):
        summary = controlled_summary("a" * 64, "CCO", "b" * 32)
        self.assertEqual(summary.endpoints, {})
        self.assertNotIn("endpoints", summary.model_dump())
        self.assertEqual(
            len(PredictionSummary.model_validate(summary.model_dump()).properties), 6
        )
        self.assertEqual(selected_endpoints(controlled_prediction()), {})

    def test_missing_units_kind_wrong_bounds_and_unsafe_keys_are_rejected_not_clamped(
        self,
    ):
        for unit, kind, value in [
            ("%", "prediction", 0.1),
            ("probability [0,1]", "descriptor", 0.1),
            ("probability [0,1]", "prediction", 1.1),
        ]:
            prediction = controlled_prediction()
            prediction.properties.append(
                Property(key="hERG", label="hERG", value=value, unit=unit, kind=kind)
            )
            with self.assertRaises(WebError):
                selected_endpoints(prediction)
        for endpoints in [
            {"hERG": True},
            {"hERG": "0.1"},
            {"hERG": float("nan")},
            {"hERG": -0.1},
            {"unknown": 0.1},
        ]:
            with self.assertRaises(ValidationError):
                PredictionSummary(endpoints=endpoints)

    def test_stale_packets_cannot_expose_risk_probabilities(self):
        with self.assertRaises(ValidationError):
            PredictionSummary(status="stale", endpoints={"hERG": 0.1})
