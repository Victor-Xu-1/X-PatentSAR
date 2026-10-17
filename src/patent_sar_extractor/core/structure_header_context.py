"""One original title-context capture/replay for physical and logical columns."""

from .source_cell_tokens import cell_lines, cell_text
from .source_observations import source_observation_status
from .source_table_markers import TABLE_CAPTION_START
from .source_table_roles import observed_role
from .source_window_chunks import observe_window_sources


def observe_header_context(tokens, size, top):
    window, starts = [0, 0, size[0], top], []
    for lane in (tokens, getattr(tokens, "native_tokens", ())):
        titles = [
            line
            for line in cell_lines(lane, window)
            if TABLE_CAPTION_START.match(cell_text(line, window))
        ]
        if titles:
            starts.append(max(0, min(part["bbox"][1] for part in titles[-1]) - 2))
    bounds = [0, min(starts), size[0], top] if starts and min(starts) < top else None
    return observe_window_sources(tokens, bounds) if bounds else []


def original_header_context_role(contexts, top, width):
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
    return observed_role([p for p in contexts if p["text"].strip()])
