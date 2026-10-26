"""One original title-context capture/replay for physical and logical columns."""

from .activity_context_geometry import context_floor
from .caption_role_titles import project_caption_titles
from .source_observations import source_observation_status
from .source_table_roles import observed_role
from .source_window_chunks import observe_window_sources
from .title_context_grids import title_context_spec


def observe_header_context(
    tokens,
    size,
    top,
    *,
    geometry=None,
    logical_window=None,
    grid_axes=None,
    page=None,
    parallel_grids=None,
    title_cache=None,
):
    def capture(bounds):
        sources = observe_window_sources(tokens, bounds) if bounds else []
        if page is None or not sources:
            return sources
        from .title_source_capture import attach_title_sources

        nominations = original_header_context_packets(
            sources, top, size[0], geometry=geometry, logical_window=logical_window
        )
        return attach_title_sources(
            page,
            sources,
            nominations,
            context=title_context_spec(
                geometry=geometry,
                logical_window=logical_window,
                grid_axes=grid_axes,
                parallel_grids=parallel_grids,
            ),
            title_cache=title_cache,
        )

    if logical_window is not None:
        if geometry is not None:
            raise ValueError(
                "Logical source capture cannot declare physical grid context"
            )
        floor = max(0, top - 310)
        return capture([0, floor, size[0], top]) if floor < top else []
    if geometry is not None:
        floor = context_floor(geometry)
        return capture([0, floor, size[0], top]) if floor < top else []
    floor = max(0, top - 310)
    return capture([0, floor, size[0], top]) if floor < top else []


def original_header_context_packets(
    contexts, top, width, *, geometry=None, logical_window=None
):
    if (
        not isinstance(contexts, list)
        or len(contexts) > 2
        or any(
            not isinstance(p, dict)
            or source_observation_status(p, p.get("bbox"), p.get("text")) == "invalid"
            or p["bbox"][3] != top
            or p["bbox"][0] != 0
            or p["bbox"][2] != width
            for p in contexts
        )
    ):
        raise ValueError("Malformed original structure-header title context")
    if geometry is not None and logical_window is not None:
        raise ValueError(
            "Original logical windows cannot declare printed-grid geometry"
        )
    if geometry is not None:
        floor = context_floor(geometry)
        if floor < top:
            expected = [0, floor, width, top]
            if not contexts or any(p["bbox"] != expected for p in contexts):
                raise ValueError(
                    "Incomplete original structure-header context geometry"
                )
            return project_caption_titles(contexts, geometry)
        if contexts:
            raise ValueError("Original zero-height header context is not empty")
    if logical_window is not None:
        floor = max(0, top - 310)
        if floor < top:
            if not contexts or any(
                p["bbox"] != [0, floor, width, top] for p in contexts
            ):
                raise ValueError("Incomplete original logical-header context window")
            return project_caption_titles(contexts, None, logical_window=logical_window)
        if contexts:
            raise ValueError("Original zero-height logical context is not empty")
    floor = max(0, top - 310)
    if floor < top:
        expected = [0, floor, width, top]
        if not contexts or any(packet["bbox"] != expected for packet in contexts):
            raise ValueError("Incomplete original header-only title context")
        return project_caption_titles(contexts, None, context_window=expected)
    if contexts:
        raise ValueError("Original zero-height title context is not empty")
    return []


def original_header_context_role(
    contexts,
    top,
    width,
    *,
    geometry=None,
    logical_window=None,
    grid_axes=None,
    parallel_grids=None,
):
    from .title_context_source import valid_title_context

    if any(not valid_title_context(context, width=width) for context in contexts):
        return "unresolved", ""
    if top == 0 and not contexts:
        return "unknown", ""
    return observed_role(
        original_header_context_packets(
            contexts, top, width, geometry=geometry, logical_window=logical_window
        ),
        contexts=contexts,
        context=title_context_spec(
            geometry=geometry,
            logical_window=logical_window,
            grid_axes=grid_axes,
            parallel_grids=parallel_grids,
        ),
    )
