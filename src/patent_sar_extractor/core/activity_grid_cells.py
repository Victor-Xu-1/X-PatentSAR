"""Physical activity-cell ownership and multiline token layout."""

from __future__ import annotations

import re
from dataclasses import replace
from itertools import pairwise

from .activity_header_metrics import normalize_metric_text
from .activity_identity import is_value, normalize_compound, normalize_value
from .activity_models import GridSchema
from .activity_values import (
    is_explicit_missing_activity_value,
    normalize_activity_value_token,
)
from .table_cells import read_cell


def continued_header_schema(
    old: GridSchema,
    current: GridSchema,
    old_xs: list[float],
    xs: list[float],
    prefix: str,
) -> GridSchema:
    """Repeated header spacing cannot create a new metric on a proved continuation."""
    if len(xs) != len(old_xs) or any(abs(a - b) > 4 for a, b in zip(xs, old_xs)):
        return current

    def canonical(text: str) -> str:
        return re.sub(r"\s+", "", normalize_metric_text(text))

    if not old.raw_headers or tuple(map(canonical, old.raw_headers)) != tuple(
        map(canonical, current.raw_headers)
    ):
        return current
    # A new caption/prose/assay is a new context, even with identical columns.
    document_id = r"(?:WO|PCT|US|EP|CN|JP|KR)\s*/?(?:[A-Z]{1,4})?\d[\w/-]*"
    running = re.compile(
        rf"{document_id}(?:\s+{document_id})*|[-–—]?\s*\d+\s*[-–—]?", re.IGNORECASE
    )
    if any(
        not running.fullmatch(line.strip())
        for line in prefix.splitlines()
        if line.strip()
    ):
        return current
    return replace(
        current, context=old.context, groups=old.groups, header_region=old.header_region
    )


def cell_tokens(
    tokens: list[dict], bounds: tuple[float, float, float, float]
) -> list[dict]:
    x0, y0, x1, y1 = bounds
    # Half-open intervals have exactly one owner, including tokens near rules.
    return [t for t in tokens if x0 <= t["x"] < x1 and y0 <= t["y"] < y1]


def cell_text(tokens: list[dict], bounds: tuple[float, float, float, float]) -> str:
    """Keep printed lines; vertical overlap joins baseline/subscript fragments."""
    lines: list[list[dict]] = []
    for token in sorted(cell_tokens(tokens, bounds), key=lambda t: (t["y"], t["x"])):
        box = token.get("bbox")
        for line in reversed(lines):
            anchor = line[0]
            other = anchor.get("bbox")
            if box and other:
                overlap = min(box[3], other[3]) - max(box[1], other[1])
                height = min(box[3] - box[1], other[3] - other[1])
                same_line = height > 0 and overlap >= 0.3 * height
            else:
                same_line = abs(token["y"] - anchor["y"]) <= 3
            if same_line:
                line.append(token)
                break
        else:
            lines.append([token])
    return "\n".join(
        " ".join(t["text"] for t in sorted(line, key=lambda t: t["x"]))
        for line in lines
    )


def crosses_cell(tokens: list[dict], bounds: tuple[float, float, float, float]) -> bool:
    """Retain a cross-rule observation but never certify its cell assignment."""
    x0, y0, x1, y1 = bounds
    return any(
        (box := token.get("bbox"))
        and (box[0] < x0 - 1 or box[1] < y0 - 1 or box[2] > x1 + 1 or box[3] > y1 + 1)
        for token in cell_tokens(tokens, bounds)
    )


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
    owned: set[int] = set()
    for group in schema.groups:
        for column in (group.id_column, *(col for col, _ in group.value_columns)):
            if (
                type(column) is not int
                or not 0 <= column < len(xs) - 1
                or column in owned
            ):
                raise ValueError(
                    "Activity grid has overlapping or invalid physical column ownership"
                )
            owned.add(column)
    if owned != set(range(len(xs) - 1)):
        raise ValueError("Activity grid has unowned physical columns")
    if schema.raw_headers and len(schema.raw_headers) != len(xs) - 1:
        raise ValueError("Activity raw headers do not match physical columns")


def read_activity_cell(
    page, tokens: list[dict], bounds, *, identifier: bool, native: bool
):
    raw = cell_text(tokens, bounds)
    crossing = crosses_cell(tokens, bounds)
    if identifier:
        value = normalize_compound(raw)
        kind = (
            "label"
            if re.match(r"Compound|Example|Cpd|Cmpd|实施例|化合物", raw, re.IGNORECASE)
            else "id"
        )
    else:
        value = normalize_value(raw)
        kind = (
            "plus"
            if re.fullmatch(r"\+{1,3}", value)
            else (
                "letter" if re.fullmatch(r"[A-D]", value, re.IGNORECASE) else "number"
            )
        )
    if native:
        # Shared lexical kinds do not support all printed suffixes, missing
        # markers or ranges. Original native tokens remain exact evidence.
        observations = [{"method": "native_cell", "text": raw}]
        return (
            value,
            observations,
            crossing or not bool(value if identifier else is_value(value)),
        )
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
    cell_proved = (
        not conflict
        and not reading.needs_review
        and any(
            observation.get("method") in {"cell_ocr_400dpi", "cell_ocr_600dpi"}
            and observation.get("text") == reading.value
            and type(observation.get("confidence")) in (float, int)
            and 0.85 <= observation["confidence"] <= 1
            for observation in observations
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
