"""Retained original text outside a visible grid; no new OCR or caption guesses."""

from itertools import pairwise

from .source_cell_tokens import cell_lines
from .source_geometry import native_region
from .source_observations import source_cell_observation, source_observation_status


def context_windows(edges, fragments):
    width, height = edges["page_size"]
    lower = min([edges["ys"][0], *(f["bbox"][1] for f in fragments)])
    upper = max([edges["ys"][-1], *(f["bbox"][3] for f in fragments)])
    return {
        "prefix": [0, 0, width, lower] if lower > 0 else None,
        "suffix": [0, upper, width, height] if upper < height else None,
    }


def _chunks(tokens, window):
    combined = [*tokens, *getattr(tokens, "native_tokens", [])]
    rows = cell_lines(combined, window)
    cuts, count = [window[1]], 0
    for index, row in enumerate(rows):
        if len(row) > 384:
            raise ValueError("Original boundary context row exceeds its token bound")
        if count + len(row) > 384:
            cut = (max(t["y"] for t in rows[index - 1]) + min(t["y"] for t in row)) / 2
            if not cuts[-1] < cut < window[3]:
                raise ValueError("Unproved original boundary-context partition")
            cuts.append(cut)
            count = 0
        count += len(row)
    cuts.append(window[3])
    if len(cuts) > 513:
        raise ValueError("Original boundary context exceeds its chunk bound")
    return [[window[0], y0, window[2], y1] for y0, y1 in pairwise(cuts)]


def observe_fragment_context(tokens, edges, fragments):
    if not fragments:
        return None
    result = {}
    for name, window in context_windows(edges, fragments).items():
        if window is None:
            result[name] = []
            continue
        result[name] = []
        for box in _chunks(tokens, window):
            native = native_region(tokens, box, False)
            sources = [source_cell_observation(tokens, box, native=native)]
            if not native:
                sources.append(source_cell_observation(tokens, box, native=True))
            result[name].append({"bbox": box, "sources": sources})
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
        bottom = window[1]
        for chunk in chunks:
            if not isinstance(chunk, dict) or set(chunk) != {"bbox", "sources"}:
                raise ValueError("Invalid original boundary-context chunk")
            box, sources = chunk["bbox"], chunk["sources"]
            if (
                not isinstance(box, list)
                or len(box) != 4
                or any(type(v) not in {int, float} for v in box)
                or box[0] != window[0]
                or box[2] != window[2]
                or not bottom == box[1] < box[3] <= window[3]
                or not isinstance(sources, list)
                or not 1 <= len(sources) <= 2
            ):
                raise ValueError("Omitted or overlapping original context window")
            bottom = box[3]
            origins = []
            for source in sources:
                if source is None:
                    origins.append(None)
                    continue
                if (
                    source_observation_status(source, box, source.get("text"))
                    == "invalid"
                ):
                    raise ValueError(
                        "Invalid original open-row context coordinates or confidence"
                    )
                origins.append(source["origin"])
            if origins not in (["native"], ["raster", "native"], [None, None]):
                raise ValueError("Foreign original open-row context origin")
        if bottom != window[3]:
            raise ValueError("Incomplete original boundary-context coverage")


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
