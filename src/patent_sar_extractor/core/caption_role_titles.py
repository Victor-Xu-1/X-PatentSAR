"""One original title projection for capture and saved catalogue-role replay."""

from .activity_caption_windows import prefix_parts, shared_caption_allowed
from .activity_context_geometry import valid_box
from .source_observations import project_source_observation, source_observation_status
from .source_table_markers import table_body_boundary


def _title_packet(packet, region):
    parts = prefix_parts(packet["tokens"], region)
    starts = [
        index
        for index, part in enumerate(parts)
        if table_body_boundary(" ".join(t["text"] for t in part))
    ]
    if not starts:
        return None
    start, title = starts[-1], list(parts[starts[-1]])
    for part in parts[start + 1 : start + 3]:
        if min(t["y"] for t in part) - max(
            t["y"] for t in title
        ) > 18 or table_body_boundary(" ".join(t["text"] for t in part)):
            break
        title.extend(part)
    if len(title) > 64:
        raise ValueError("Original caption title token budget exceeded")
    bounds = [
        min(t["bbox"][0] for t in title),
        min(t["bbox"][1] for t in title),
        max(t["bbox"][2] for t in title) + 0.001,
        max(t["bbox"][3] for t in title) + 0.001,
    ]
    projected = project_source_observation(packet, bounds)
    if len(projected["tokens"]) > 64:
        raise ValueError("Original caption title scope exceeds its token budget")
    return projected


def project_caption_titles(sources, geometry, *, logical_window=None):
    if not isinstance(sources, list) or not 1 <= len(sources) <= 2:
        raise ValueError("Malformed original caption context inventory")
    for packet in sources:
        if (
            source_observation_status(packet, packet.get("bbox"), packet.get("text"))
            == "invalid"
        ):
            raise ValueError("Invalid original caption context observation")
    if geometry is not None and logical_window is not None:
        raise ValueError("Original logical windows are not printed-grid geometry")
    box = geometry["table_bbox"] if geometry is not None else logical_window
    if not valid_box(box):
        raise ValueError("Invalid original caption projection window")
    region = {
        "xs": [box[0], box[2]],
        "ys": [box[1], box[3]],
    }
    if geometry is None:
        region.update(original_band=[box[0], box[2]], allow_shared_caption=False)
    else:
        region["context_geometry"] = geometry
        region["allow_shared_caption"] = shared_caption_allowed(
            (packet["tokens"] for packet in sources), region
        )
    return [
        part
        for packet in sources
        if (part := _title_packet(packet, region)) is not None
    ]
