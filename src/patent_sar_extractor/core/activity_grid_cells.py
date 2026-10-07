"""Physical activity-cell ownership and multiline token layout."""

from __future__ import annotations

from itertools import pairwise

from .activity_models import GridSchema


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
