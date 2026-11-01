"""Capture catalogue roles from the existing original context authority."""

from .activity_context_geometry import (
    context_floor,
    context_region,
    grid_axes,
    grid_box,
)
from .caption_frame_inventory import complete_prefixed_frame
from .caption_role_proof import observed_role
from .caption_role_titles import project_caption_titles
from .source_geometry import SourceTokens, native_region
from .source_observations import source_cell_observation
from .title_context_grids import parallel_title_grids, title_context_spec
from .title_original_replay import reuse_title_sources
from .title_source_capture import attach_title_sources


def owns_caption_frame(
    page, region, regions, tokens, boxes, *, original_role=None, original_captions=()
):
    """A current original caption catalogue must not inherit unrelated columns."""
    from .caption_grid_rows import caption_rows
    from .caption_role_proof import caption_role_status

    role = observe_caption_role(
        page, region, regions, tokens, original_role=original_role
    )
    if role is None:
        return False  # Untyped transport cannot prove a current caption owner.
    if original_role is not None:
        claimed = caption_role_status(original_role, page.number + 1, grid_box(region))
        fields = {"role", "table_key", "continuation"}
        if claimed not in {"compound", "nonfinal", "unknown"} or {
            key: value for key, value in original_role.items() if key not in fields
        } != {key: value for key, value in role.items() if key not in fields}:
            return False
        role = original_role
    status = caption_role_status(role, page.number + 1, grid_box(region))
    if status == "nonfinal":
        return True
    if status not in {"compound", "unknown"}:
        return False
    _rows, kinds = caption_rows(region, tokens, boxes, role)
    if status == "unknown":
        return complete_prefixed_frame(
            page.number + 1, region, role, kinds, original_captions
        )
    return "label" in kinds and "drawing" in kinds


def observe_caption_role(
    page, region, regions, tokens, *, original_role=None, title_cache=None
):
    """Reuse original context; unknown observed titles may use bounded cell reads."""
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
    peers = parallel_title_grids(geometry, regions)
    context = title_context_spec(
        geometry=geometry,
        grid_axes=grid_axes(region),
        parallel_grids=peers,
        page_grids=[grid_axes(grid) for grid in regions] if peers is not None else None,
    )
    sources = (
        attach_title_sources(
            page, sources, observed, context=context, title_cache=title_cache
        )
        if original_role is None
        else reuse_title_sources(page, sources, original_role.get("sources"))
    )
    if sources is None:
        return None
    observed = project_caption_titles(sources, geometry)
    role, key = observed_role(observed, contexts=sources, context=context)
    scope = {
        "version": 1,
        "page_no": page.number + 1,
        "table_bbox": grid_box(region),
        "grid_axes": grid_axes(region),
        "context_geometry": geometry,
        "window": window,
        "observations": observed,
        "sources": sources,
        **({"parallel_grids": peers} if peers is not None else {}),
        **({"page_grids": context["page_grids"]} if peers is not None else {}),
        "role": role,
        "table_key": key,
    }
    return scope
