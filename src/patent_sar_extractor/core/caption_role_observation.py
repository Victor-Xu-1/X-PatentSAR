"""Capture catalogue roles from the existing original context authority."""

from .activity_context_geometry import (
    context_floor,
    context_region,
    grid_axes,
    grid_box,
)
from .caption_role_proof import observed_role
from .caption_role_titles import project_caption_titles
from .source_geometry import SourceTokens, native_region
from .source_observations import source_cell_observation


def owns_caption_frame(page, region, regions, tokens, boxes, *, original_role=None):
    """A current original caption catalogue must not inherit unrelated columns."""
    from .caption_grid_rows import caption_rows
    from .caption_role_proof import caption_role_status

    role = observe_caption_role(page, region, regions, tokens)
    if role is None:
        return False  # Untyped transport cannot prove a current caption owner.
    if original_role is not None:
        claimed = caption_role_status(original_role, page.number + 1, grid_box(region))
        fields = {"role", "table_key", "continuation"}
        if claimed not in {"compound", "nonfinal"} or {
            key: value for key, value in original_role.items() if key not in fields
        } != {key: value for key, value in role.items() if key not in fields}:
            return False
        role = original_role
    status = caption_role_status(role, page.number + 1, grid_box(region))
    if status == "nonfinal":
        return True
    if status != "compound":
        return False
    _rows, kinds = caption_rows(region, tokens, boxes, role)
    return "label" in kinds and "drawing" in kinds


def observe_caption_role(page, region, regions, tokens):
    """No extra OCR: reuse the current original token and grid inventory."""
    if not isinstance(tokens, SourceTokens):
        return None
    geometry = context_region(region, [grid_box(item) for item in regions])[
        "context_geometry"
    ]
    window = [0, context_floor(geometry), page.rect.width, region["ys"][0]]
    if window[1] >= window[3]:
        return None
    native = native_region(tokens, window, False)
    sources = [source_cell_observation(tokens, window, native=native)]
    if not native:
        sources.append(source_cell_observation(tokens, window, native=True))
    observed = project_caption_titles(sources, geometry)
    role, key = observed_role(observed)
    return {
        "version": 1,
        "page_no": page.number + 1,
        "table_bbox": grid_box(region),
        "grid_axes": grid_axes(region),
        "context_geometry": geometry,
        "window": window,
        "observations": observed,
        "sources": sources,
        "role": role,
        "table_key": key,
    }
