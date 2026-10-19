"""Retain native CSV context namespaces; never turn an import into source proof."""

import json
import re

from pydantic import ValidationError

from ...core.sar.study_conditions import missing_condition
from ..activity_scope_models import ActivityScopeFields
from ..errors import WebError

NATIVE_HEADERS = frozenset(
    {
        "review_only",
        "acceptance_state",
        "compound_id",
        "smiles",
        "metric",
        "value",
        "structure_molfile_json",
    }
)


def native_headers(headers):
    return NATIVE_HEADERS.issubset(headers)


def _condition_object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Duplicate original condition key")
    return value


def native_scope_fields(row):
    fields = {
        key: row.get(key, "").strip() or None
        for key in ("source_scope", "source_table", "source_context_page")
    }
    if (
        all(value is None for value in fields.values())
        and not row.get("source_conditions_json", "").strip()
    ):
        return {}
    raw = row.get("source_conditions_json", "").strip()
    if raw:
        if len(raw) > 10000:
            raise WebError(
                422,
                "sar_csv_context_origin",
                "Original condition metadata exceeds its bound.",
            )
        try:
            fields["source_conditions"] = json.loads(
                raw, object_pairs_hook=_condition_object
            )
        except (ValueError, RecursionError) as error:
            raise WebError(
                422, "sar_csv_context_origin", "Original condition metadata is invalid."
            ) from error
    page = fields["source_context_page"]
    if page is not None:
        if not re.fullmatch(r"[0-9]{1,5}", page):
            raise WebError(
                422, "sar_csv_context_origin", "Original context page is invalid."
            )
        fields["source_context_page"] = int(page)
    try:
        return ActivityScopeFields.model_validate(fields).model_dump()
    except ValidationError as error:
        raise WebError(
            422, "sar_csv_context_origin", "Original context identity is invalid."
        ) from error


def native_conditions(context, fields):
    result = dict(context)
    conditions = dict(fields.get("source_conditions", {}))
    duration = conditions.get("treatment_duration")
    if not missing_condition(duration):
        explicit = conditions.get("duration")
        if not missing_condition(explicit) and explicit != duration:
            raise WebError(
                422,
                "sar_csv_context_conflict",
                "Original duration conditions conflict.",
            )
        conditions["duration"] = duration
        conditions.pop("treatment_duration")
    for name, value in conditions.items():
        if (
            not missing_condition(result.get(name))
            and not missing_condition(value)
            and result[name] != value
        ):
            raise WebError(
                422,
                "sar_csv_context_conflict",
                "Mapped and original conditions conflict.",
            )
        if name not in result or missing_condition(result[name]):
            result[name] = value
    if result.get("duration") is None and result.get("treatment_duration") is not None:
        result["duration"] = result.pop("treatment_duration")
    return result
