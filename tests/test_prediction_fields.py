"""Controlled six-metric contract tests, not scientific model-accuracy claims."""

import unittest

from pydantic import ValidationError

from patent_sar_extractor.web.analysis_models import Prediction, Property
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.prediction_fields import METRICS, selected_metrics
from patent_sar_extractor.web.prediction_models import PredictionSummary
from patent_sar_extractor.workers.analysis_protocol import ADMET_BUNDLE_SHA256


def controlled_prediction() -> Prediction:
    values = (46.07, -0.1, 20.23, 1.0, 1.0, -1.25)
    return Prediction(
        smiles="CCO",
        properties=[
            Property(key=key, label=label, value=value, unit=unit, kind=kind)
            for (key, (label, unit, kind)), value in zip(METRICS.items(), values)
        ],
    )


class PredictionFieldTests(unittest.TestCase):
    def test_six_ordered_metrics_preserve_negative_log_values_and_real_units(self):
        metrics = selected_metrics(controlled_prediction())
        self.assertEqual(
            [metric.label for metric in metrics],
            ["MW", "LogP", "TPSA", "HBD", "HBA", "LogS"],
        )
        self.assertEqual(metrics[1].value, -0.1)
        self.assertEqual(metrics[5].unit, "log(mol/L)")
        self.assertEqual(metrics[5].kind, "prediction")
        self.assertTrue(all(metric.kind == "descriptor" for metric in metrics[:5]))

    def test_missing_wrong_units_or_fractional_counts_are_not_success(self):
        for case in ("missing", "unit", "count", "kind"):
            with self.subTest(case=case):
                value = controlled_prediction()
                if case == "missing":
                    value.properties.pop()
                elif case == "unit":
                    value.properties[-1].unit = "mg/mL"
                elif case == "count":
                    value.properties[3].value = 1.5
                else:
                    value.properties[-1].kind = "descriptor"
                with self.assertRaises(WebError):
                    selected_metrics(value)

    def test_complete_requires_source_engine_and_all_six_fields(self):
        with self.assertRaises(ValidationError):
            PredictionSummary(
                status="complete", properties=selected_metrics(controlled_prediction())
            )
        summary = PredictionSummary(
            status="complete",
            properties=selected_metrics(controlled_prediction()),
            source_fingerprint="a" * 64,
            smiles_sha256="b" * 64,
            generated_at="2026-10-03T00:00:00Z",
            job_id="d" * 32,
            engine={
                "name": "ADMET-AI",
                "version": "2.0.1",
                "model_sha256": ADMET_BUNDLE_SHA256,
            },
        )
        self.assertTrue(summary.review_only)

    def test_stale_values_and_nonfinite_scalars_are_rejected(self):
        with self.assertRaises(ValidationError):
            PredictionSummary(
                status="stale", properties=selected_metrics(controlled_prediction())
            )
        with self.assertRaises(ValidationError):
            Property(
                key="logP",
                label="LogP",
                value=float("nan"),
                unit="log-ratio",
                kind="descriptor",
            )
