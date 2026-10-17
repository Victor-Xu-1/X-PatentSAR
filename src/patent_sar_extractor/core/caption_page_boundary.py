"""Two adjacent original caption grids, never an inferred compound sequence."""

from dataclasses import dataclass
from itertools import pairwise

from .activity_context_geometry import MAX_TABLES, grid_box
from .caption_boundary_context import valid_caption_tail
from .caption_role_links import role_link, valid_role_link
from .caption_role_proof import caption_role_status
from .structure_table_headers import aligned_column_edges


@dataclass(frozen=True)
class CaptionGridCarry:
    page_no: int
    axes: dict
    direction: str | None
    role: dict | None
    trailing_drawing: bool = False
    tail: dict | None = None
    pending: tuple[dict, ...] = ()


def adjacent_caption_grid(carry, page_no, region, role, new_table):
    """Nominate one adjacent grid; original-role proof still owns acceptance."""
    return bool(
        carry
        and carry.page_no + 1 == page_no
        and region["ys"][0] < 150
        and aligned_column_edges(carry.axes["xs"], region["xs"])
        and (
            not new_table
            or role
            and carry.role
            and role["table_key"] == carry.role["table_key"]
        )
    )


def qualified_caption_carries(carries):
    """Qualify each original frame once, not once per possible next-page frame.

    These are call-local immutable observations, not saved scientific acceptance.
    The formal role/cell consumers independently replay the retained proof.
    """
    if len(carries) > MAX_TABLES:
        raise ValueError("Original caption page exceeds its frame resource bound")
    return [
        (index, carry)
        for index, carry in enumerate(carries)
        if caption_role_status(carry.role, carry.page_no, grid_box(carry.axes))
        in {"compound", "nonfinal"}
        and valid_caption_tail(carry.tail, carry.role)
    ]


def _proved_pair(previous, current, direction, tail):
    if direction not in {"above", "below"} or not all(
        isinstance(role, dict) for role in (previous, current)
    ):
        return False
    try:
        if any(
            caption_role_status(role, role["page_no"], role["table_bbox"]) != "compound"
            for role in (previous, current)
        ):
            return False
        if current["window"][1] != 0 or not valid_caption_tail(tail, previous):
            return False
        link = role_link(
            previous, previous["grid_axes"], current["grid_axes"], direction, tail
        )
        if "continuation" in current and current["continuation"] != link:
            return False
        return valid_role_link(
            current,
            link,
            "compound",
            previous["table_key"],
            current["table_key"],
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def caption_boundary_proof(previous, current, direction, tail):
    """Keep the other original role beside the already retained label role."""
    if not _proved_pair(previous, current, direction, tail):
        return None
    return {
        "version": 1,
        "other_role": current if direction == "above" else previous,
        "previous_tail": tail,
    }


def _column(axes, cell):
    return next(
        (
            index
            for index, edges in enumerate(pairwise(axes["xs"]))
            if edges == (cell[0], cell[2])
        ),
        None,
    )


def valid_caption_page_boundary(ownership, label_page, diagram_page, label, drawing):
    """Replay both original frames, their direction and the exact boundary cells."""
    packet = ownership.get("page_boundary")
    if (
        not isinstance(packet, dict)
        or set(packet) != {"version", "other_role", "previous_tail"}
        or type(packet["version"]) is not int
        or packet["version"] != 1
    ):
        return False
    direction, label_role = ownership.get("direction"), ownership.get("caption_role")
    other = packet["other_role"]
    previous, current = (
        (label_role, other) if direction == "above" else (other, label_role)
    )
    if not _proved_pair(previous, current, direction, packet["previous_tail"]):
        return False
    earlier, later = previous["page_no"], current["page_no"]
    if (label_page, diagram_page) != (
        (earlier, later) if direction == "above" else (later, earlier)
    ):
        return False
    label_axes, drawing_axes = label_role["grid_axes"], other["grid_axes"]
    label_row = label_axes["ys"][-2:] if direction == "above" else label_axes["ys"][:2]
    drawing_row = (
        drawing_axes["ys"][:2] if direction == "above" else drawing_axes["ys"][-2:]
    )
    column = _column(label_axes, label)
    return bool(
        column is not None
        and column == _column(drawing_axes, drawing)
        and (label[1], label[3]) == tuple(label_row)
        and (drawing[1], drawing[3]) == tuple(drawing_row)
    )
