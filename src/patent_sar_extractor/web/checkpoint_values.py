"""Path-only checkpoint transforms over the canonical bounded source graph."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Any

from patent_sar_extractor.artifact_nodes import JsonGraph

from .errors import WebError


def checkpoint_graph(value, transform, *, depth, max_depth, field=None):
    graph = JsonGraph(max_depth=max_depth, transform=transform)
    try:
        root = graph.visit(value, depth, field=field)
        graph.validate_allocation(root)
    except ValueError as exc:
        raise WebError(
            422,
            "checkpoint_limit",
            "Checkpoint nesting or expansion exceeds its limit.",
        ) from exc
    return graph, root


def relocate_value(
    value: Any,
    *,
    source: Path,
    target: Path,
    relative: Callable,
    path_keys: AbstractSet[str],
    depth: int,
    max_depth: int,
    path_field: bool,
) -> Any:
    def move(item, field):
        if isinstance(item, str) and (field in path_keys or field is True) and item:
            if item == str(source):
                return str(target)
            if item.startswith(str(source) + "/") or not Path(item).is_absolute():
                return str(target / relative(item))
        return item

    graph, root = checkpoint_graph(
        value,
        move,
        depth=depth,
        max_depth=max_depth,
        field=True if path_field else None,
    )
    return graph.materialize(root)


def copy_images(
    value: Any,
    *,
    image_keys: AbstractSet[str],
    relative: Callable,
    present: Callable,
    publish: Callable,
    depth: int,
    max_depth: int,
) -> None:
    def inspect(item, field):
        if field not in image_keys or not item:
            return item
        if not isinstance(item, str):
            raise WebError(
                422, "invalid_checkpoint", "Checkpoint image reference is invalid."
            )
        path = relative(item)
        if path.parts[0] not in {"structures", "structure_bindings", "smiles"} or (
            path.suffix.lower()
            not in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
        ):
            raise WebError(
                409,
                "unsafe_checkpoint",
                "Checkpoint asset is outside its approved stage.",
            )
        if not present(str(path)):
            publish(str(path))
        return item

    checkpoint_graph(value, inspect, depth=depth, max_depth=max_depth)
