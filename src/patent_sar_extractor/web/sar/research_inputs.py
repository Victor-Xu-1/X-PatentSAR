"""Capture existing effective scientific evidence; never invoke another model."""

from __future__ import annotations

import math

from ..errors import WebError
from ..lead_chemistry import validated_endpoints
from ..lead_endpoints import LEAD_ENDPOINTS, validate_endpoints
from ..prediction_models import METRIC_KEYS
from ..property_values import effective_property_values, validate_overrides


def project_evidence(compound) -> dict:
    values = effective_property_values(compound)
    origins = {}
    for key in METRIC_KEYS:
        if key in compound.property_overrides:
            origins[key] = "manual_null" if values[key] is None else "manual"
        elif values[key] is not None:
            origins[key] = (
                "verified_project_descriptor"
                if key != "Solubility_AqSolDB"
                else "verified_project_model"
            )
    # Current graph/source/producer identity is checked by research_compounds
    # through MolecularObservationStore. An incomplete cache is not a prediction.
    predictions = validated_endpoints(compound) or {}
    return {
        "properties": dict(values),
        "property_origins": origins,
        "predictions": predictions,
        "prediction_origin": "verified_project_model"
        if predictions
        else "not_provided",
    }


def validate_mapping(mapping, headers: list[str]) -> None:
    if not set(mapping.property_columns).issubset(METRIC_KEYS) or not set(
        mapping.prediction_columns
    ).issubset(LEAD_ENDPOINTS):
        raise WebError(422, "sar_csv_mapping", "Unknown research evidence column role.")
    selected = [
        *mapping.property_columns.values(),
        *mapping.prediction_columns.values(),
    ]
    activity_roles = {
        mapping.id_column,
        mapping.smiles_column,
        *mapping.activity_columns,
    }
    if len(selected) != len(set(selected)) or any(
        column not in headers or column in activity_roles for column in selected
    ):
        raise WebError(
            422, "sar_csv_mapping", "Research roles require distinct existing columns."
        )


def csv_evidence(row: dict[str, str], mapping) -> dict:
    def values(columns):
        result = {}
        for key, column in columns.items():
            raw = row[column].strip()
            if not raw:
                result[key] = None
                continue
            try:
                number = float(raw)
            except ValueError as error:
                raise WebError(
                    422,
                    "sar_csv_evidence",
                    "Mapped research evidence must be numeric or blank.",
                ) from error
            if not math.isfinite(number):
                raise WebError(
                    422, "sar_csv_evidence", "Research evidence must be finite."
                )
            result[key] = number
        return result

    properties, predictions = (
        values(mapping.property_columns),
        values(mapping.prediction_columns),
    )
    try:
        validate_overrides(properties)
        validate_endpoints(
            {key: value for key, value in predictions.items() if value is not None}
        )
    except ValueError as error:
        raise WebError(
            422,
            "sar_csv_evidence",
            "Research evidence violates its declared property or probability semantics.",
        ) from error
    return {
        "properties": properties,
        "property_origins": {key: "imported" for key in properties},
        "predictions": predictions,
        "prediction_origin": "imported" if predictions else "not_provided",
    }
