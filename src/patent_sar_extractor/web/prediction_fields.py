"""The reviewed default six metrics, selected from genuine ADMET-AI output."""

from __future__ import annotations

import hashlib
import json

from patent_sar_extractor.workers.analysis_protocol import (
    ADMET_BUNDLE_SHA256,
    ADMET_VERSION,
)

from .analysis_models import Prediction
from .errors import WebError
from .prediction_models import METRIC_KEYS, METRIC_SPECS, PredictionMetric

METRICS = METRIC_SPECS


def selected_metrics(prediction: Prediction) -> list[PredictionMetric]:
    if len({metric.key for metric in prediction.properties}) != len(
        prediction.properties
    ):
        raise WebError(502, "admet_protocol", "ADMET property keys are duplicated.")
    supplied = {metric.key: metric for metric in prediction.properties}
    result = []
    for key in METRIC_KEYS:
        label, unit, kind = METRICS[key]
        metric = supplied.get(key)
        if metric is None or metric.unit != unit or metric.kind != kind:
            raise WebError(
                502,
                "admet_protocol",
                "ADMET did not supply the reviewed six metrics and units.",
            )
        if (
            key
            in {
                "molecular_weight",
                "tpsa",
                "hydrogen_bond_donors",
                "hydrogen_bond_acceptors",
            }
            and metric.value < 0
        ):
            raise WebError(
                502, "admet_protocol", "Computed molecular descriptors are invalid."
            )
        if (
            key in {"hydrogen_bond_donors", "hydrogen_bond_acceptors"}
            and not metric.value.is_integer()
        ):
            raise WebError(
                502, "admet_protocol", "Computed hydrogen-bond counts are not integers."
            )
        result.append(
            PredictionMetric(
                key=key, label=label, value=metric.value, unit=unit, kind=kind
            )
        )
    return result


def prediction_epoch() -> str:
    return hashlib.sha256(
        json.dumps(
            [
                1,
                "source-bound-producer-envelope",
                ADMET_VERSION,
                ADMET_BUNDLE_SHA256,
                list(METRICS.items()),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
