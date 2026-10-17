"""Nominate actual printed frames before constructing any numbered cells."""

from .activity_header_identity import (
    measurement_header_identity,
    measurement_header_roles,
)
from .logical_column_partitions import nominate_unruled_headers, nomination_groups
from .ruled_continuation_context import validate_page_grid
from .ruled_structure_headers import observe_ruled_header
from .source_body_context import contained_source_diagrams
from .source_cell_tokens import cell_text
from .structure_column_scopes import original_columns_fit_frame
from .structure_table_headers import (
    aligned_column_edges,
    structure_column_pairs,
)
from .unruled_continuation_titles import anchor_scope
from .unruled_header_readings import original_header_readings


def nominate_physical_frames(tokens, grids, diagrams, previous, size):
    """Hints select inspection only; source scopes still prove every owner."""
    headers, pending = [], []
    anchors = [
        anchor
        for section in previous
        if (anchor := anchor_scope(section["source"]["header_scope"])) is not None
    ]
    logical_hints = nominate_unruled_headers(tokens, size)
    unheaded = []
    for grid in grids:
        validate_page_grid(grid, size)
        xs, ys = grid["xs"], grid["ys"]
        if len(xs) < 3 or len(ys) < 3:
            continue
        raw = [
            cell_text(tokens, [xs[c], ys[0], xs[c + 1], ys[1]])
            for c in range(len(xs) - 1)
        ]
        if structure_column_pairs(raw):
            headers.append(grid)
        else:
            unheaded.append(grid)
    for grid in unheaded:
        xs, ys = grid["xs"], grid["ys"]
        if (
            contained_source_diagrams(diagrams, [xs[0], ys[0], xs[-1], ys[-1]])
            or any(original_columns_fit_frame(anchor, xs) for anchor in anchors)
            or any(
                original["ys"][-1] <= ys[0] and aligned_column_edges(original["xs"], xs)
                for original in headers
            )
            or any(
                len(groups) == len(xs) - 1
                and max(g["bbox"][3] for g in groups) < ys[0]
                and all(
                    left <= group["bbox"][0] < group["bbox"][2] <= right
                    for group, left, right in zip(groups, xs[:-1], xs[1:], strict=True)
                )
                for hint in logical_hints
                for groups in [nomination_groups(hint)]
            )
        ):
            pending.append(grid)
    return headers, pending


def known_measurement_frame(page, tokens, grid, original_sha):
    """A diagram-free frame needs positive original roles before exclusion.

    Unknown/contradictory columns are not silently removed. This reads only the
    physical header through the shared original-source reader; activity rows
    remain owned by the normal activity inventory and extraction chain.
    """
    xs, ys = grid["xs"], grid["ys"]
    raw = [
        cell_text(tokens, [xs[c], ys[0], xs[c + 1], ys[1]]) for c in range(len(xs) - 1)
    ]
    roles = measurement_header_roles(raw)
    if roles is None:
        return False
    scope = observe_ruled_header(page, tokens, grid, original_sha)
    headers = original_header_readings(
        scope["role_cells"],
        xs,
        ys[:2],
        scope["source_observations"],
        identity=measurement_header_identity,
    )
    return headers is not None and measurement_header_roles(headers) == roles
