"""Original caption readings and spatial ownership, shared formal source gate."""

import math
from collections.abc import Mapping

from .numbered_structure_pairs import _box, _confirmed_observations, _label


def valid_caption_binding_evidence(binding):
    packet = binding.get("exact_caption_evidence")
    if not isinstance(packet, Mapping):
        return False
    label = _label(binding.get("cpd") or binding.get("compound_id"))
    diagram_page, label_page = binding.get("page_no"), packet.get("page_no")
    label_box = _box(packet.get("bbox"))
    diagram = _box([binding.get("struct_" + axis) for axis in ("x0", "y0", "x1", "y1")])
    observations, ownership = packet.get("observations"), packet.get("ownership")
    if not (
        label
        and binding.get("structure_id")
        and type(diagram_page) is int
        and type(label_page) is int
        and 0 < label_page <= diagram_page
        and label_box
        and diagram
        and isinstance(observations, (list, tuple))
        and 1 <= len(observations) <= 3
        and _confirmed_observations(label, observations)
        and isinstance(ownership, Mapping)
    ):
        return False
    if not ownership:
        # Same literal below-diagram anchor used by the source observer, not
        # nearest-neighbor distance, synthesis order or guessed continuation.
        x, y = (label_box[0] + label_box[2]) / 2, (label_box[1] + label_box[3]) / 2
        return bool(
            label_page == diagram_page
            and diagram[0] <= x <= diagram[2]
            and diagram[3] - 32 <= y <= diagram[3] + 24
        )
    cell, original_label = (
        _box(ownership.get("structure_cell")),
        _box(ownership.get("label_cell")),
    )
    if not (
        ownership.get("kind") == "ruled_caption"
        and type(ownership.get("structure_page_no")) is int
        and ownership["structure_page_no"] == diagram_page
        and original_label == label_box
        and cell
        and all(math.isclose(cell[i], label_box[i], abs_tol=0.01) for i in (0, 2))
        and cell[0] - 2 <= diagram[0] < diagram[2] <= cell[2] + 2
        and cell[1] - 2 <= diagram[1] < diagram[3] <= cell[3] + 2
    ):
        return False
    direction = ownership.get("direction")
    if label_page != diagram_page:
        return direction == "above" and label_page + 1 == diagram_page
    return bool(
        direction == "above"
        and math.isclose(label_box[3], cell[1], abs_tol=0.01)
        or direction == "below"
        and math.isclose(label_box[1], cell[3], abs_tol=0.01)
    )
