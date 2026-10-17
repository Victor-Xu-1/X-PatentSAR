"""Literal table-caption nominations shared by original source consumers."""

from .activity_context_geometry import context_region, grid_box
from .caption_role_semantics import catalog_title_role
from .source_cell_tokens import cell_lines, cell_text
from .source_table_markers import TABLE_CAPTION_START
from .source_table_roles import title_key
from .structure_table_headers import header_groups


def caption_line_parts(line):
    """Split only independent caption starts after an original physical gap."""
    if not TABLE_CAPTION_START.match(" ".join(part["text"] for part in line)):
        return [line]  # Several prose references do not become new table titles.
    starts = [
        group["bbox"][0]
        for group in header_groups(line)
        if TABLE_CAPTION_START.match(group["text"])
    ]
    if len(starts) < 2:
        return [line]
    return [
        [
            part
            for part in line
            if left <= part["x"] and (right is None or part["x"] < right)
        ]
        for left, right in zip(starts, [*starts[1:], None], strict=True)
    ]


def caption_context_geometry(caption, captions, grids):
    """Only explicit lateral titles and one actual frame localize a declaration.

    A sole title keeps the established shared/global interpretation. Ambiguous
    frame associations retain the complete source instead of inventing a band.
    """
    box = caption["bbox"]
    if not any(
        min(box[3], other["bbox"][3]) > max(box[1], other["bbox"][1])
        and (box[2] <= other["bbox"][0] or other["bbox"][2] <= box[0])
        for other in captions
    ):
        return None
    candidates = [
        grid
        for grid in grids
        if grid["ys"][0] >= box[3] and grid["xs"][0] - 4 <= box[0] < grid["xs"][-1]
    ]
    if not candidates:
        return None
    top = min(grid["ys"][0] for grid in candidates)
    candidates = [grid for grid in candidates if grid["ys"][0] == top]
    if len(candidates) != 1:
        return None
    return context_region(candidates[0], [grid_box(grid) for grid in grids])[
        "context_geometry"
    ]


def table_caption_nominees(tokens, size, *, native_tokens=()):
    """Keep distinct original positions/claims; never parse a prose reference."""
    window = [0, 0, *size]
    output, seen, primary = [], set(), []
    for lane_index, lane in enumerate(
        (tokens, native_tokens or getattr(tokens, "native_tokens", ()))
    ):
        for line in (
            part
            for original in cell_lines(lane, window)
            for part in caption_line_parts(original)
        ):
            text = cell_text(line, window)
            if not TABLE_CAPTION_START.match(text):
                continue
            box = [
                min(p["bbox"][0] for p in line),
                min(p["bbox"][1] for p in line),
                max(p["bbox"][2] for p in line),
                max(p["bbox"][3] for p in line),
            ]
            identity = (title_key(text), catalog_title_role(text))
            # Unknown literal keys still have an exact raw identity, not a
            # fabricated number or a shared empty-key equivalence class.
            identity = identity if identity[0] else (*identity, text.casefold())
            key = (text, tuple(box))
            duplicate = lane_index == 1 and any(
                old_identity == identity
                and min(old["bbox"][2], box[2]) > max(old["bbox"][0], box[0])
                and min(old["bbox"][3], box[3]) > max(old["bbox"][1], box[1])
                for old, old_identity in primary
            )
            if key not in seen and not duplicate:
                seen.add(key)
                nomination = {"text": text, "bbox": box}
                output.append(nomination)
                if lane_index == 0:
                    primary.append((nomination, identity))
    return output
