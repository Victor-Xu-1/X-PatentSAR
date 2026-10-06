"""Manual property overlays, never changes to model evidence or its producer."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .prediction_models import METRIC_KEYS, MetricKey

if TYPE_CHECKING:
    from .models import Compound

PropertyValue = float | int | None
PropertyOverrides = dict[MetricKey, PropertyValue]


def validate_overrides(value: object) -> object:
    if not isinstance(value, dict) or len(value) > 6:
        raise ValueError("Provide at most six manual property values")
    for key, scalar in value.items():
        if key not in METRIC_KEYS:
            raise ValueError("Unknown manual property key")
        if scalar is None:
            continue
        if type(scalar) not in {int, float} or abs(scalar) > 1e308:
            raise ValueError("Manual property must be a finite numeric value or null")
        if not math.isfinite(scalar):
            raise ValueError("Manual property must be finite")
        if (
            key
            in {
                "molecular_weight",
                "tpsa",
                "hydrogen_bond_donors",
                "hydrogen_bond_acceptors",
            }
            and scalar < 0
        ):
            raise ValueError("MW, TPSA and hydrogen-bond counts cannot be negative")
        if key in {"hydrogen_bond_donors", "hydrogen_bond_acceptors"} and scalar != int(
            scalar
        ):
            raise ValueError("Hydrogen-bond counts must be integers")
    return value


def manual_property_values(row: Compound) -> PropertyOverrides:
    if row.correction and row.correction.stale:
        return {}
    return row.property_overrides


def effective_property_values(row: Compound) -> PropertyOverrides:
    """Null is an explicit manual value, not permission to borrow a prediction."""
    values: PropertyOverrides = dict.fromkeys(METRIC_KEYS)
    if row.admet and row.admet.status == "complete":
        values.update((metric.key, metric.value) for metric in row.admet.properties)
    if row.descriptors and row.descriptors.status == "complete":
        values.update(
            (metric.key, metric.value) for metric in row.descriptors.properties
        )
    values.update(manual_property_values(row))
    return values
