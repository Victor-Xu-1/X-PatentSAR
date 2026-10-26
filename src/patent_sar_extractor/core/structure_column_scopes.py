"""Original header interface; continuations are consumers, never new anchors."""

from .logical_column_partitions import nomination_groups
from .ruled_structure_headers import ruled_header_roles
from .structure_header_context import original_header_context_packets
from .structure_table_headers import aligned_column_edges
from .title_ink_geometry import title_context_spec
from .unruled_structure_headers import header_windows, unruled_header_roles


def original_column_axes(scope):
    if scope.get("kind") == "original_ruled_columns":
        return scope["grid_axes"]["xs"], scope["grid_axes"]["ys"][:2]
    return header_windows(
        scope["nomination"],
        scope["page_size"],
        scope["column_selection"],
        scope["column_band"],
    )


def original_column_groups(scope):
    return nomination_groups(
        {"groups": scope["nomination"], "selection": scope["column_selection"]}
    )


def original_column_headers(scope):
    return (
        scope["nomination"]
        if scope.get("kind") == "original_ruled_columns"
        else [g["text"] for g in original_column_groups(scope)]
    )


def original_column_roles(scope):
    return (
        ruled_header_roles(scope)
        if scope.get("kind") == "original_ruled_columns"
        else unruled_header_roles(scope)
    )


def original_column_title_args(scope):
    xs, ys = original_column_axes(scope)
    logical_window = (
        [xs[0], ys[0], xs[-1], ys[-1]]
        if scope.get("kind") is None
        and scope["column_band"] != [0, scope["page_size"][0]]
        else None
    )
    return {
        "contexts": scope["context_sources"],
        "context": title_context_spec(
            geometry=scope.get("context_geometry"),
            logical_window=logical_window,
            grid_axes=scope.get("grid_axes")
            if scope.get("kind") == "original_ruled_columns"
            else None,
        ),
    }


def original_column_context(scope):
    _xs, ys = original_column_axes(scope)
    context = original_column_title_args(scope)["context"]
    return original_header_context_packets(
        scope["context_sources"],
        ys[0],
        scope["page_size"][0],
        geometry=context["geometry"],
        logical_window=context["logical_window"],
    )


def original_columns_fit_frame(scope, xs):
    """Printed rules align exactly; logical columns retain their original words.

    Logical outer clipping windows are not printed table edges. A later actual
    frame may narrow those windows only when each complete original header is
    inside its corresponding physical column. Never move a header or add one.
    """
    roles = original_column_roles(scope)
    if roles is None or not aligned_column_edges(xs, xs):
        return False
    if scope.get("kind") == "original_ruled_columns":
        return aligned_column_edges(original_column_axes(scope)[0], xs)
    groups = original_column_groups(scope)
    return len(groups) == len(xs) - 1 and all(
        left <= group["bbox"][0] < group["bbox"][2] <= right
        for group, left, right in zip(groups, xs[:-1], xs[1:], strict=True)
    )
