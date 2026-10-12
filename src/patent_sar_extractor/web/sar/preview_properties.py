"""Conservative arithmetic on explicit property provenance, not desirability."""

import math
from dataclasses import dataclass

from .preview_models import PropertyComparisonStatus

# These are the actual current snapshot/descriptor producers. Unknown future
# labels retain their raw values but need an explicit reviewed comparison rule.
COMPARABLE_ORIGINS = frozenset(
    {
        "computed_rdkit",
        "imported",
        "manual",
        "verified_project_descriptor",
        "verified_project_model",
    }
)


@dataclass(frozen=True, slots=True)
class PropertyComparisons:
    differences: dict[str, float | None]
    statuses: dict[str, PropertyComparisonStatus]


def property_comparisons(reference, candidate) -> PropertyComparisons:
    differences, statuses = {}, {}
    for key in dict.fromkeys([*reference.properties, *candidate.properties]):
        left, right = reference.properties.get(key), candidate.properties.get(key)
        first, second = (
            reference.property_origins.get(key),
            candidate.property_origins.get(key),
        )
        difference = None
        if left is None or right is None:
            status = "missing"
        elif first not in COMPARABLE_ORIGINS or second not in COMPARABLE_ORIGINS:
            status = "origin_unknown"
        elif first != second:
            status = "origin_mismatch"
        else:
            value = right - left
            if math.isfinite(value):
                status, difference = "comparable", value
            else:
                status = "not_representable"
        differences[key], statuses[key] = difference, status
    return PropertyComparisons(differences, statuses)
