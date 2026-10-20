"""Physical activity-cell ownership and multiline token layout."""

from __future__ import annotations

import re
from itertools import pairwise

from .activity_continuation_policy import continuation_prefix
from .activity_identity import is_value, normalize_compound, normalize_value
from .activity_metadata import metadata_role
from .activity_models import GridSchema
from .activity_values import (
    is_explicit_missing_activity_value,
    normalize_activity_value_token,
)
from .cell_cross_observation import printed_cross_valid
from .source_cell_claims import cell_source_conflict, cell_source_status
from .source_cell_tokens import cell_text, cell_tokens, crosses_cell
from .source_geometry import native_region
from .source_observations import source_cell_observation
from .source_paint_visibility import native_paint_view, visible_native_tokens
from .table_cells import activity_kind_matches, read_cell

__all__ = [
    "cell_text",
    "cell_tokens",
    "continuation_prefix",
    "crosses_cell",
    "read_activity_cell",
    "validate_grid",
]


def validate_grid(region: dict, schema: GridSchema) -> None:
    """Invalid physical ownership fails before reading or losing any values."""
    xs, ys = region["xs"], region["ys"]
    if (
        len(xs) < 2
        or len(ys) < 2
        or any(right <= left for edges in (xs, ys) for left, right in pairwise(edges))
    ):
        raise ValueError("Activity grid boundaries must be ordered")
    if not 0 <= schema.first_data_row <= len(ys) - 1:
        raise ValueError("Activity grid data-row boundary is invalid")
    if schema.raw_headers and len(schema.raw_headers) != len(xs) - 1:
        raise ValueError("Activity raw headers do not match physical columns")
    owned: set[int] = set()
    for group in schema.groups:
        for column in (
            group.id_column,
            *(col for col, _ in group.value_columns),
            *(col for col, _ in group.metadata_columns),
        ):
            if (
                type(column) is not int
                or not 0 <= column < len(xs) - 1
                or column in owned
            ):
                raise ValueError(
                    "Activity grid has overlapping or invalid physical column ownership"
                )
            owned.add(column)
        for column, kind in group.metadata_columns:
            if (
                not schema.raw_headers
                or metadata_role(schema.raw_headers[column]) != kind
            ):
                raise ValueError("Activity count column has no original header proof")
    if owned != set(range(len(xs) - 1)):
        raise ValueError("Activity grid has unowned physical columns")
    values = {col for group in schema.groups for col, _ in group.value_columns}
    if (
        schema.semantic_kind not in {"generic", "biology"}
        or type(schema.needs_review) is not bool
        or not isinstance(schema.value_kinds, tuple)
        or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or type(pair[0]) is not int
            or pair[0] not in values
            or pair[1] not in {"number", "letter", "plus"}
            for pair in schema.value_kinds
        )
        or len({col for col, _ in schema.value_kinds}) != len(schema.value_kinds)
        or schema.semantic_kind == "generic"
        and bool(schema.value_kinds)
        or schema.semantic_kind == "biology"
        and {col for col, _ in schema.value_kinds} != values
    ):
        raise ValueError("Activity grid has unproved original value roles")


def read_activity_cell(
    page,
    tokens: list[dict],
    bounds,
    *,
    identifier: bool,
    native: bool,
    kind: str | None = None,
):
    declared_kind = kind
    native = native_region(tokens, bounds, native)
    raw = cell_text(tokens, bounds)
    crossing = crosses_cell(tokens, bounds)
    if identifier:
        value = normalize_compound(raw)
        kind = kind or (
            "label"
            if re.match(r"Compound|Example|Cpd|Cmpd|实施例|化合物", raw, re.IGNORECASE)
            else "id"
        )
    else:
        value = normalize_value(raw)
        kind = kind or (
            "plus"
            if re.fullmatch(r"\+{1,3}", value)
            else (
                "letter"
                if re.fullmatch(r"[A-G](?:[12])?", value, re.IGNORECASE)
                else "number"
            )
        )
    if native:
        # Shared lexical kinds do not support all printed suffixes, missing
        # markers or ranges. Original native tokens remain exact evidence.
        observations = [{"method": "native_cell", "text": raw}]
        profile = source_cell_observation(tokens, bounds, native=True)
        visible = True
        if profile is not None:
            observations[0].update(bbox=list(bounds), source_observation=profile)
            if tokens.native_paint_view is None:
                tokens.native_paint_view = native_paint_view(page)
            visible = visible_native_tokens(
                page, profile, paint_view=tokens.native_paint_view
            )
        role_conflict = bool(
            not identifier
            and declared_kind
            and not activity_kind_matches(value, declared_kind)
        )
        return (
            value,
            observations,
            crossing
            or role_conflict
            or not visible
            or cell_source_status(observations[0])
            not in {"legacy", "qualified", "empty"}
            or not bool(value if identifier else is_value(value)),
        )
    if not identifier and is_explicit_missing_activity_value(value):
        kind = "number"
    reading = read_cell(page, bounds, tokens, kind, False)
    refined = (
        normalize_compound(reading.value)
        if identifier
        else normalize_value(reading.value)
    )
    observations = list(reading.observations)
    if not any(o.get("text") == raw for o in observations):
        observations.insert(0, {"method": "page_ocr_cell", "text": raw})
    # Shared scalar OCR cannot erase comparators, classes, units or missing
    # markers. Conflicting reads retain the raw cell and require review.
    conflict = bool(
        value and refined and re.sub(r"\s+", "", value) != re.sub(r"\s+", "", refined)
    )
    original = next((o for o in observations if o.get("method") == "page_ocr_cell"), {})
    if "source_observation" in original:
        conflict = cell_source_conflict(original, refined, kind)
        if (
            cell_source_status(original) in {"unqualified", "empty"}
            and not conflict
            and not reading.needs_review
        ):
            value = refined
    if (
        not identifier
        and is_explicit_missing_activity_value(value)
        and (
            normalize_activity_value_token(value)
            == normalize_activity_value_token(refined)
        )
    ):
        conflict = False
    # A malformed low-resolution observation is not a competing measurement.
    # Accept only two independent high-resolution reads of the complete cell;
    # valid disagreements and qualifiers/footnotes stay explicitly unresolved.
    consensus = {
        observation.get("method")
        for observation in observations
        if observation.get("text") == refined
        and type(observation.get("confidence")) in (float, int)
        and 0.85 <= observation["confidence"] <= 1
    }
    recovered = bool(
        not identifier
        and not is_value(value)
        and is_value(refined)
        and not reading.needs_review
        and {"cell_ocr_400dpi", "cell_ocr_600dpi"}.issubset(consensus)
        and not re.search(r"[<>≤≥%±*]|(?:pM|nM|[uµμ]M|mM|mg/kg)\b", value)
    )
    if recovered:
        value, conflict = refined, False
    crosses = any(printed_cross_valid(o, bounds, refined) for o in observations)
    if (
        not identifier
        and crosses
        and not reading.needs_review
        and (re.fullmatch(r"\+{1,5}", value) or not is_value(value))
    ):
        # A page-level locator is not a count of the whole original cell.
        # Complete printed components can qualify it; native conflicts remain.
        value, conflict = refined, False
    cell_proved = (
        not conflict
        and not reading.needs_review
        and (
            crosses
            or any(
                observation.get("method") in {"cell_ocr_400dpi", "cell_ocr_600dpi"}
                and (
                    normalize_compound(observation.get("text", ""))
                    == normalize_compound(reading.value)
                    if identifier
                    else observation.get("text") == reading.value
                )
                and type(observation.get("confidence")) in (float, int)
                and 0.85 <= observation["confidence"] <= 1
                for observation in observations
            )
        )
    )
    # A detector's padded box is not the value's ownership proof. Agreement
    # with the independently clipped original cell supplies that proof.
    review = (
        (crossing and not cell_proved)
        or conflict
        or reading.needs_review
        or not reading.value
    )
    return value or refined, observations, review
