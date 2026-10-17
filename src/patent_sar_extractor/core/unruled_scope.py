"""One column-scope interface for actual headers and original continuation links."""

from .ruled_column_continuation import KIND, physical_continuation_roles
from .structure_column_scopes import (
    original_column_axes,
    original_column_headers,
    original_column_roles,
)
from .unruled_continuation import continuation_axes, continuation_roles
from .unruled_continuation_titles import anchor_scope


def scope_axes(scope):
    if scope.get("kind") == KIND:
        return scope["grid_axes"]["xs"], scope["grid_axes"]["ys"][:2]
    return (
        continuation_axes(scope)
        if scope.get("kind") == "continued_unruled_columns"
        else original_column_axes(scope)
    )


def scope_headers(scope):
    anchor = anchor_scope(scope)
    return original_column_headers(anchor) if anchor is not None else []


def scope_roles(scope):
    if scope.get("kind") == KIND:
        return physical_continuation_roles(scope)
    return (
        continuation_roles(scope)
        if scope.get("kind") == "continued_unruled_columns"
        else original_column_roles(scope)
    )


def scope_body_top(scope):
    """No header is fabricated above a physical continuation's first data row."""
    return scope_axes(scope)[1][0 if scope.get("kind") == KIND else 1]
