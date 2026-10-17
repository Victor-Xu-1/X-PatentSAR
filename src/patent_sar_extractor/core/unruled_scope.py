"""One column-scope interface for actual headers and original continuation links."""

from .unruled_continuation import continuation_axes, continuation_roles
from .unruled_continuation_titles import anchor_scope
from .unruled_structure_headers import header_windows, unruled_header_roles


def scope_axes(scope):
    return (
        continuation_axes(scope)
        if scope.get("kind") == "continued_unruled_columns"
        else header_windows(scope["nomination"], scope["page_size"])
    )


def scope_headers(scope):
    return [g["text"] for g in anchor_scope(scope)["nomination"]]


def scope_roles(scope):
    return (
        continuation_roles(scope)
        if scope.get("kind") == "continued_unruled_columns"
        else unruled_header_roles(scope)
    )
