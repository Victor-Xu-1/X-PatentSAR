"""One original caption/column selector for producers and stored source replay."""

from .activity_context_geometry import context_band, context_floor
from .source_table_captions import caption_line_parts
from .source_table_markers import TABLE_CAPTION_START, TABLE_MARKER


def _window_parts(tokens, region):
    top = region["ys"][0]
    geometry = region.get("context_geometry")
    floor = context_floor(geometry) if geometry is not None else max(0, top - 310)
    floor = max(floor, region.get("context_start", floor))
    lines = {}
    for token in tokens:
        if floor <= token["y"] < top:
            lines.setdefault(round(token["y"] / 3), []).append(token)
    output = []
    for _, row in sorted(lines.items()):
        output.extend(caption_line_parts(sorted(row, key=lambda t: t["x"])))
    return output


def _captions(parts, region):
    span = region.get("context_geometry", {}).get("parallel_span")
    return [
        part
        for part in parts
        if span is not None
        and TABLE_CAPTION_START.match(part[0]["text"])
        and TABLE_MARKER.search(" ".join(t["text"] for t in part))
        and span[0] <= part[0]["x"] < span[1]
    ]


def shared_caption_allowed(domains, region):
    """Count physical caption positions across sources, never vote on fields."""
    positions = []
    for tokens in domains:
        for part in _captions(_window_parts(tokens, region), region):
            point = part[0].get("bbox", (part[0]["x"], part[0]["y"]))[:2]
            if not any(
                abs(point[0] - x) <= 4 and abs(point[1] - y) <= 4 for x, y in positions
            ):
                positions.append(tuple(point))
                if len(positions) > 1:
                    return False
    return bool(positions)


def prefix_parts(tokens, region):
    """Keep complete owned captions and column-local conditions unchanged."""
    geometry = region.get("context_geometry")
    band = context_band(geometry) if geometry is not None else None
    original = _window_parts(tokens, region)
    allowed = region.get("allow_shared_caption")
    if allowed is None:
        native = getattr(getattr(tokens, "layout", None), "native", ())
        allowed = shared_caption_allowed((tokens, native), region)
    captions = _captions(original, region) if allowed else []
    shared = captions[0] if len(captions) == 1 else None
    output = []
    for part in original:
        if part is shared:
            output.append(part)
        elif band is not None:
            if TABLE_CAPTION_START.match(part[0]["text"]):
                if band[0] <= part[0]["x"] < band[1]:
                    output.append(part)
            else:
                owned = [t for t in part if band[0] <= t["x"] < band[1]]
                if owned:
                    output.append(owned)
        elif not (
            TABLE_MARKER.search(" ".join(t["text"] for t in part))
            and part[0].get("bbox", [part[0]["x"]])[0] > region["xs"][0] + 8
        ):
            # Historic source packets without grid geometry remain readable;
            # current writers and proof contracts always carry the inventory.
            output.append(part)
    return output
