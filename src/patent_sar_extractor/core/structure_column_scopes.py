"""Original header interface; continuations are consumers, never new anchors."""

from .ruled_structure_headers import ruled_header_roles
from .unruled_structure_headers import header_windows, unruled_header_roles


def original_column_axes(scope):
    if scope.get("kind") == "original_ruled_columns":
        return scope["grid_axes"]["xs"], scope["grid_axes"]["ys"][:2]
    return header_windows(scope["nomination"], scope["page_size"])


def original_column_headers(scope):
    return (
        scope["nomination"]
        if scope.get("kind") == "original_ruled_columns"
        else [g["text"] for g in scope["nomination"]]
    )


def original_column_roles(scope):
    return (
        ruled_header_roles(scope)
        if scope.get("kind") == "original_ruled_columns"
        else unruled_header_roles(scope)
    )
