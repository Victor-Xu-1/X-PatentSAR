"""Whole-study ordering before pagination; no client-page extrema or grade math."""

from __future__ import annotations

from ...core.identifier_order import natural_identifier_key
from ...core.sar.values import grade_ranks, parse_value
from ..errors import WebError
from ..prediction_models import METRIC_KEYS


def order_rows(rows, report, column: str = "label", direction: str = "asc"):
    policies = {policy.context_id: policy for policy in report.policies}
    allowed = (
        {"label", "lead"}
        | {"property:" + key for key in METRIC_KEYS}
        | {"context:" + key for key in policies}
    )
    if column not in allowed or direction not in {"asc", "desc"}:
        raise WebError(
            422,
            "sar_study_sort",
            "Choose a source identifier, selected activity, property or Lead column.",
        )
    # Natural identifiers are the stable tie-breaker for all modes.
    base = sorted(
        rows, key=lambda row: (natural_identifier_key(row.label), row.molecule_id)
    )
    if column == "label":
        return list(reversed(base)) if direction == "desc" else base

    def value(row):
        if column == "lead":
            return row.priority_group
        if column.startswith("property:"):
            return row.properties.get(column[9:])
        policy = policies[column[8:]]
        values = row.values.get(policy.context_id, [])
        try:
            parsed = {
                parse_value(raw, grade_ranks(policy.grade_order)) for raw in values
            }
        except ValueError:
            return None
        if len(parsed) != 1:
            return None
        current = next(iter(parsed))
        if current.kind == "ordinal":
            return grade_ranks(policy.grade_order)[current.grade]
        return current.low if current.kind == "scalar" else None

    known, unknown = [], []
    for row in base:
        scalar = value(row)
        (unknown if scalar is None else known).append(
            row if scalar is None else (scalar, row)
        )
    known.sort(key=lambda item: item[0], reverse=direction == "desc")
    return [row for _, row in known] + unknown
