"""One original title-context capture/replay for physical and logical columns."""

from .activity_context_geometry import context_floor
from .caption_role_titles import project_caption_titles
from .source_cell_tokens import cell_lines, cell_text
from .source_observations import source_observation_status
from .source_table_markers import table_body_boundary
from .source_table_roles import observed_role
from .source_window_chunks import observe_window_sources


def observe_header_context(tokens, size, top, *, geometry=None, logical_window=None):
    if logical_window is not None:
        if geometry is not None:
            raise ValueError(
                "Logical source capture cannot declare physical grid context"
            )
        floor = max(0, top - 310)
        return (
            observe_window_sources(tokens, [0, floor, size[0], top])
            if floor < top
            else []
        )
    if geometry is not None:
        floor = context_floor(geometry)
        return (
            observe_window_sources(tokens, [0, floor, size[0], top])
            if floor < top
            else []
        )
    window, starts = [0, 0, size[0], top], []
    for lane in (tokens, getattr(tokens, "native_tokens", ())):
        titles = [
            line
            for line in cell_lines(lane, window)
            if table_body_boundary(cell_text(line, window))
        ]
        if titles:
            starts.append(max(0, min(part["bbox"][1] for part in titles[-1]) - 2))
    bounds = [0, min(starts), size[0], top] if starts and min(starts) < top else None
    return observe_window_sources(tokens, bounds) if bounds else []


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
    return [p for p in contexts if p["text"].strip()]


def original_header_context_role(
    contexts, top, width, *, geometry=None, logical_window=None
):
    return observed_role(
        original_header_context_packets(
            contexts, top, width, geometry=geometry, logical_window=logical_window
        )
    )
