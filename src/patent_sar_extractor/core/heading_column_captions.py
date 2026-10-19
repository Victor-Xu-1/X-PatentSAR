"""Exact local catalogue titles and their original pixel frames, never a lane."""

import hashlib
import math
import re

from .heading_source_geometry import heading_bounds
from .source_cell_tokens import cell_lines, cell_text
from .source_observations import source_observation_status
from .source_table_markers import caption_table_marker, table_marker_identity
from .structure_catalogs import catalog_for_scope
from .structure_column_scopes import original_column_context


def _same_title(text, box, line):
    # Independent page/cell OCR may split spaces differently. Never change a
    # non-whitespace character or equate a table identifier with its whole title.
    if re.sub(r"\s+", "", text) != re.sub(r"\s+", "", line["text"]):
        return False
    other = line["bbox"]
    intersection = max(0, min(box[2], other[2]) - max(box[0], other[0])) * max(
        0, min(box[3], other[3]) - max(box[1], other[1])
    )
    area = (box[2] - box[0]) * (box[3] - box[1])
    other_area = (other[2] - other[0]) * (other[3] - other[1])
    return intersection >= 0.8 * max(area, other_area)


def column_caption_boxes(scope, page):
    """The existing context projector owns title-to-column qualification."""
    catalog = catalog_for_scope(scope)
    if not catalog.identifier:
        return []
    result = []
    for packet in original_column_context(scope):
        if (
            source_observation_status(packet, packet["bbox"], packet["text"])
            != "qualified"
        ):
            return []
        for parts in cell_lines(packet["tokens"], packet["bbox"]):
            text = cell_text(parts, packet["bbox"])
            marker = caption_table_marker(text)
            if (
                marker is None
                or table_marker_identity(marker.group()) != catalog.identifier
            ):
                continue
            box = [
                min(p["bbox"][0] for p in parts),
                min(p["bbox"][1] for p in parts),
                max(p["bbox"][2] for p in parts),
                max(p["bbox"][3] for p in parts),
            ]
            matches = [
                line["bbox"] for line in page["lines"] if _same_title(text, box, line)
            ]
            if len(matches) == 1 and matches[0] not in result:
                result.append(matches[0])
    if len(result) > 8:
        raise ValueError("Original local catalogue title budget exceeded")
    return result


def caption_frame_at(original, bounds):
    """Retain one caller-owned original frame through the shared renderer."""
    from .table_cells import cell_image

    rendered = []
    for dpi in (400, 600):
        image = cell_image(original, bounds, dpi)
        rendered.append(
            {
                "dpi": dpi,
                "shape": list(image.shape),
                "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
            }
        )
    return {"bbox": bounds, "rendered_frames": rendered}


def capture_caption_frames(original, boxes, page_size):
    """Retain source pixels only; use the shared renderer without a text model."""
    return [
        caption_frame_at(original, list(heading_bounds(box, page_size)))
        for box in boxes
    ]


def valid_caption_frames(frames, boxes, page_size):
    if not isinstance(frames, list) or len(frames) != len(boxes):
        return False
    for saved, box in zip(frames, boxes, strict=True):
        bounds = list(heading_bounds(box, page_size))
        if (
            not isinstance(saved, dict)
            or set(saved) != {"bbox", "rendered_frames"}
            or saved["bbox"] != bounds
            or not isinstance(saved["rendered_frames"], list)
            or len(saved["rendered_frames"]) != 2
        ):
            return False
        for frame, dpi in zip(saved["rendered_frames"], (400, 600), strict=True):
            if (
                not isinstance(frame, dict)
                or set(frame) != {"dpi", "shape", "pixel_sha256"}
                or type(frame["dpi"]) is not int
                or frame["dpi"] != dpi
                or not isinstance(frame["shape"], list)
                or len(frame["shape"]) != 3
                or any(type(n) is not int or n <= 0 for n in frame["shape"])
                or frame["shape"][2] != 3
                or math.prod(frame["shape"][:2]) > 8_000_000
                or not isinstance(frame["pixel_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", frame["pixel_sha256"])
                or abs(frame["shape"][1] - (bounds[2] - bounds[0] - 3) * dpi / 72) > 2
                or abs(frame["shape"][0] - (bounds[3] - bounds[1] - 2.4) * dpi / 72) > 2
            ):
                return False
    return True
