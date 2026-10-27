"""Conservative original path ownership when a PDF form disrupts sequence IDs."""

from collections import Counter, defaultdict


def _sequence_fits(paints, path):
    order = path.get("seqno")
    if type(order) is not int or not 0 <= order < len(paints):
        return False
    kind, box = paints[order]
    if kind not in {"fill-path", "stroke-path"} or path.get("type") not in {
        "s",
        "f",
        "fs",
    }:
        return False
    if (
        path["type"] == "s"
        and kind != "stroke-path"
        or path["type"] == "f"
        and kind != "fill-path"
    ):
        return False
    rect = path.get("rect")
    return rect is not None and (
        box[0] <= rect[0] <= rect[2] <= box[2]
        and box[1] <= rect[1] <= rect[3] <= box[3]
    )


def _axial_stroke_box(path):
    """Only a complete single axial segment has an exact simple paint envelope."""
    items, width = path.get("items"), path.get("width")
    if (
        path.get("type") != "s"
        or path.get("closePath")
        or not isinstance(items, list)
        or len(items) != 1
        or items[0][0] != "l"
        or type(width) not in {int, float}
        or not 0 < width <= 4
    ):
        return None
    first, last = items[0][1:]
    if first == last or first.x != last.x and first.y != last.y:
        return None
    half = width / 2
    return (
        min(first.x, last.x) - half,
        min(first.y, last.y) - half,
        max(first.x, last.x) + half,
        max(first.y, last.y) + half,
    )


def original_path_owners(paints, drawings):
    """One source adapter, never a sequence offset or nearest-box assignment.

    Preserve normal engine identity when its complete sequence is consistent.
    On an inconsistent page, retain only unique EXACT simple-stroke envelopes.
    Unmapped/duplicate/complex records remain unknown paints, not table rules.
    Paired original pixels and the normal rule validator still own admission.
    Raw engine records, including their original seqno, are not rewritten.
    """
    if all(_sequence_fits(paints, path) for path in drawings) and len(
        {path["seqno"] for path in drawings}
    ) == len(drawings):
        return {path["seqno"]: path for path in drawings}
    candidates, owners = defaultdict(list), {}
    paint_counts = Counter(tuple(box) for kind, box in paints if kind == "stroke-path")
    for path in drawings:
        box = _axial_stroke_box(path)
        if box is not None:
            candidates[box].append(path)
    for order, (kind, box) in enumerate(paints):
        matching = candidates.get(tuple(box), ())
        if (
            kind == "stroke-path"
            and paint_counts[tuple(box)] == 1
            and len(matching) == 1
        ):
            owners[order] = matching[0]
    return owners
