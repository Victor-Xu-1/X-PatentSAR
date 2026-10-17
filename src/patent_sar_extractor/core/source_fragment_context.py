"""Retained original text outside a visible grid; no new OCR or caption guesses."""

from .source_observations import source_observation_status
from .source_window_chunks import observe_source_window, validate_source_window


def context_windows(edges, fragments):
    width, height = edges["page_size"]
    lower = min([edges["ys"][0], *(f["bbox"][1] for f in fragments)])
    upper = max([edges["ys"][-1], *(f["bbox"][3] for f in fragments)])
    return {
        "prefix": [0, 0, width, lower] if lower > 0 else None,
        "suffix": [0, upper, width, height] if upper < height else None,
    }


def observe_fragment_context(tokens, edges, fragments):
    if not fragments:
        return None
    result = {}
    for name, window in context_windows(edges, fragments).items():
        if window is None:
            result[name] = []
            continue
        result[name] = observe_source_window(tokens, window)
    return result


def validate_fragment_context(region):
    context = region.get("fragment_context")
    fragments = region["row_fragments"]
    if not fragments:
        if context is not None:
            raise ValueError("A closed grid has asserted open-row context")
        return
    if not isinstance(context, dict) or set(context) != {"prefix", "suffix"}:
        raise ValueError("Missing original open-row boundary context")
    for name, window in context_windows(region["grid_edges"], fragments).items():
        chunks = context[name]
        if not isinstance(chunks, list) or (
            window is None
            and chunks
            or window is not None
            and not 1 <= len(chunks) <= 512
        ):
            raise ValueError("Malformed original open-row boundary sources")
        if window is None:
            continue
        validate_source_window(chunks, window, allow_legacy=True)


def boundary_texts(region, name):
    context = region.get("fragment_context")
    if context is None:
        return None
    texts = []
    for chunk in context[name]:
        for source in chunk["sources"]:
            if source is None or source_observation_status(
                source, source.get("bbox"), source.get("text")
            ) not in {"qualified", "empty"}:
                return None
            texts.append(source["text"])
    return texts or [""]
