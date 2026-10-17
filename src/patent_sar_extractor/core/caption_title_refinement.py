"""Bounded original-title rereads through the existing physical-cell authority."""

from .activity_context_geometry import valid_box
from .caption_role_semantics import catalog_title_role
from .source_geometry import native_region
from .source_observations import project_source_observation
from .source_table_roles import title_key
from .unruled_header_readings import original_header_readings


def title_refinement_bounds(scope):
    """Only an already observed complete caption nominates a pixel window."""
    packets, window = scope["observations"], scope["window"]
    if not packets or not 1 <= len(packets) <= 2 or not valid_box(window):
        return None
    boxes = [packet["bbox"] for packet in packets]
    if any(not valid_box(box) for box in boxes):
        return None
    bounds = [
        max(window[0], min(b[0] for b in boxes) - 3),
        max(window[1], min(b[1] for b in boxes) - 3),
        min(window[2], max(b[2] for b in boxes) + 3),
        min(window[3], max(b[3] for b in boxes) + 3),
    ]
    return bounds if valid_box(bounds) and bounds[3] - bounds[1] <= 128 else None


def _identity(text):
    return catalog_title_role(text), title_key(text)


def _source_conflict(original, selected):
    role, key = _identity(original)
    final_role, final_key = _identity(selected)
    return bool(role != "unknown" and role != final_role or key and key != final_key)


def refined_title_role(scope):
    """Recheck coordinates, complete reads and known original semantic vetoes."""
    refinement = scope.get("refinement")
    if (
        not isinstance(refinement, dict)
        or set(refinement) != {"version", "bbox", "role_cells"}
        or type(refinement["version"]) is not int
        or refinement["version"] != 1
    ):
        return None
    bounds = title_refinement_bounds(scope)
    if bounds is None or refinement["bbox"] != bounds:
        return None
    try:
        sources = [project_source_observation(p, bounds) for p in scope["sources"]]
        headers = original_header_readings(
            refinement["role_cells"],
            [bounds[0], bounds[2]],
            [bounds[1], bounds[3]],
            sources,
            identity=_identity,
            source_conflict=_source_conflict,
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if headers is None or any(
        _source_conflict(packet["text"], headers[0]) for packet in scope["observations"]
    ):
        return None
    # A proved mixed/unknown title is still not a final catalogue. Keeping that
    # role also lets an explicit continued title reach the existing carry gate.
    return _identity(headers[0])


def observe_title_refinement(page, scope, tokens):
    """Unknown raster/vector titles only; no whole-page pass or new OCR engine."""
    from .activity_grid_role_observation import observe_role_cells

    bounds = title_refinement_bounds(scope)
    if bounds is None or native_region(tokens, bounds, False):
        return None
    reading = observe_role_cells(
        page,
        {"xs": [bounds[0], bounds[2]], "ys": [bounds[1], bounds[3]]},
        tokens,
        retain_frames=True,
    )
    return (
        {"version": 1, "bbox": bounds, "role_cells": reading}
        if reading is not None
        else None
    )


def confirmed_title_texts(scope):
    """The same proved full title supplies continuation words, not raw guesses."""
    if "refinement" not in scope:
        return tuple(packet["text"] for packet in scope["observations"])
    if refined_title_role(scope) is None:
        return ()
    reading = scope["refinement"]["role_cells"]["observations"][0]
    return (reading["matrix"][0][0],)
