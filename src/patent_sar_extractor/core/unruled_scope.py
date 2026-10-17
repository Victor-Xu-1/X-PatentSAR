"""One column-scope interface for actual headers and original continuation links."""

from .structure_column_scopes import (
    original_column_axes,
    original_column_headers,
    original_column_roles,
)
from .unruled_continuation import continuation_axes, continuation_roles
from .unruled_continuation_titles import anchor_scope


def scope_axes(scope):
    return (
        continuation_axes(scope)
        if scope.get("kind") == "continued_unruled_columns"
        else original_column_axes(scope)
    )


def scope_headers(scope):
    return original_column_headers(anchor_scope(scope))


def scope_roles(scope):
    return (
        continuation_roles(scope)
        if scope.get("kind") == "continued_unruled_columns"
        else original_column_roles(scope)
    )
