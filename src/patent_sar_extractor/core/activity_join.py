"""Exact activity left join for export/QA; repeated source observations survive."""

from __future__ import annotations

from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    artifact_identity_matches,
)

from .activity_identity import is_control, is_value, normalize_compound


def _measurement_fields(row: dict) -> list[tuple[str, str]]:
    if not isinstance(row.get("cpd"), str):
        raise ValueError("Malformed activity compound identifier")
    fields = []
    for name in ("activity_values", "cell_line_data"):
        bucket = row.get(name, {})
        if not isinstance(bucket, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in bucket.items()
        ):
            raise ValueError("Malformed activity measurement fields")
        fields.extend(bucket.items())
    return fields


def activity_order_and_map(
    rows: list[dict],
) -> tuple[list[str], dict[str, dict[str, str]]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Malformed activity observation rows")
    collected: dict[str, dict[str, list[str]]] = {}
    order = []
    for row in rows:
        fields = _measurement_fields(row)
        label = normalize_compound(row.get("cpd", ""))
        if not label or is_control(label):
            continue
        if not fields:
            continue
        if label not in collected:
            order.append(label)
        for key, value in fields:
            collected.setdefault(label, {}).setdefault(key, []).append(value)
    return order, {
        label: {key: " | ".join(values) for key, values in fields.items()}
        for label, fields in collected.items()
    }


def activity_for_compound(data: dict, compound: str) -> dict:
    # No parent, child, suffix, slash-expansion or source-order inference.
    return data.get(normalize_compound(compound), {})


def activity_evidence_errors(
    payload: dict, classified_activity_pages: list[int] | None = None
) -> list[str]:
    """Validate observed rows, not measured/numeric membership.

    Shape/identity errors are technical failures. Missing observations and source
    review findings are scientific failures. Explicit unavailable values remain
    observations and are never converted to zero or discarded.
    """
    if not artifact_identity_matches(payload, ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION):
        raise ValueError("Malformed or incompatible activity producer output")
    if classified_activity_pages is not None and (
        not isinstance(classified_activity_pages, list)
        or any(type(page) is not int or page < 0 for page in classified_activity_pages)
    ):
        raise ValueError("Malformed activity classification proof")
    rows = payload.get("rows")
    order, _ = activity_order_and_map(rows)
    errors = []
    if not rows:
        if classified_activity_pages != []:
            errors.append(
                "No activity rows without classification proof that activity is absent."
            )
        return errors
    if classified_activity_pages == []:
        errors.append(
            "Observed activity rows contradict the absent-activity classification."
        )
    review = [
        row.get("cpd")
        for row in rows
        if row.get("needs_review") and not is_control(row.get("cpd", ""))
    ]
    if review:
        errors.append(f"Activity observations require review ({review[:12]}).")
    for row in rows:
        if is_control(row["cpd"]):
            continue
        if not normalize_compound(row["cpd"]):
            errors.append(f"Unproved activity compound identifier: {row['cpd']!r}.")
        fields = _measurement_fields(row)
        if not fields or any(
            not key.strip() or not value.strip() for key, value in fields
        ):
            errors.append(f"Activity row has empty measurement fields: {row['cpd']!r}.")
        elif any(
            not is_value(value) and value.strip() not in {"—", "–"}
            for _, value in fields
        ):
            errors.append(
                f"Activity row has unrecognized original values: {row['cpd']!r}."
            )
    if not order:
        errors.append("No original compound activity observations were extracted.")
    return errors
