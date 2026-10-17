"""Column adapters over the sole original body-context and diagram authority."""

from .source_body_context import original_context_extent, validate_page_diagrams
from .structure_table_headers import structure_column_pairs
from .unruled_scope import scope_axes, scope_body_top, scope_headers


def body_context_window(scope):
    return [0, scope_body_top(scope), *scope["page_size"]]


def original_body_extent(scope, chunks, diagrams):
    validate_page_diagrams(diagrams, scope["page_size"])
    return original_context_extent(chunks, body_context_window(scope), diagrams)


def original_body_bottom(scope, chunks, diagrams):
    return original_body_extent(scope, chunks, diagrams)["body_bottom"]


def column_body_extent(source):
    """Recompute inventory/trusted bounds from the same complete source facts."""
    return original_body_extent(
        source["header_scope"], source["body_context"], source["page_diagrams"]
    )


def column_boundary_issues(extent):
    return [
        {"cpd": "", "reason": "unproved_original_column_boundary", "boundary": boundary}
        for boundary in extent["unproved_boundaries"]
    ]


def trusted_column_diagrams(source, diagrams):
    bottom = column_body_extent(source)["trusted_bottom"]
    return [diagram for diagram in diagrams if diagram["bbox"][3] <= bottom]


def body_diagrams(scope, bottom, diagrams):
    xs, ys = scope_axes(scope)
    pairs = structure_column_pairs(scope_headers(scope))
    return [
        d
        for d in diagrams
        if d["bbox"][3] > ys[1]
        and d["bbox"][1] < bottom
        and any(
            min(d["bbox"][2], xs[s + 1]) > max(d["bbox"][0], xs[s]) for _, s in pairs
        )
    ]
