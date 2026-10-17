"""Nominate actual printed frames before constructing any numbered cells."""

from .activity_header_identity import compact_header
from .activity_header_metrics import METRIC, normalize_metric_text
from .activity_identity import is_id_header
from .activity_metadata import metadata_role
from .ruled_continuation_context import validate_page_grid
from .ruled_structure_headers import observe_ruled_header
from .source_body_context import contained_source_diagrams
from .source_cell_tokens import cell_text
from .structure_column_scopes import original_columns_fit_frame
from .structure_table_headers import structure_column_pairs, structure_header_role
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
        elif contained_source_diagrams(diagrams, [xs[0], ys[0], xs[-1], ys[-1]]) or any(
            original_columns_fit_frame(anchor, xs) for anchor in anchors
        ):
            pending.append(grid)
    return headers, pending


def _measurement_role(text):
    """Reuse the activity header identities, not a second endpoint classifier."""
    if is_id_header(text):
        return "identifier"
    if structure_header_role(text) == "structure":
        return "structure"
    if METRIC.search(normalize_metric_text(text)):
        return "measurement:" + compact_header(text)
    role = metadata_role(text)
    return "metadata:" + role if role else ""


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
    roles = [_measurement_role(text) for text in raw]
    if (
        "identifier" not in roles
        or not all(roles)
        or "structure" in roles
        or not any(role.startswith("measurement:") for role in roles)
    ):
        return False
    scope = observe_ruled_header(page, tokens, grid, original_sha)
    headers = original_header_readings(
        scope["role_cells"],
        xs,
        ys[:2],
        scope["source_observations"],
        identity=_measurement_role,
    )
    return headers is not None and [_measurement_role(h) for h in headers] == roles
