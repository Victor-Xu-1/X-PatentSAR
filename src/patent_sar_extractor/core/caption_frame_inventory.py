"""Complete original caption-cell facts, not successful molecule assignments."""

from collections.abc import Mapping

from .caption_reading_proof import confirmed_caption_readings
from .caption_source_windows import caption_windows


def complete_prefixed_frame(page_no, region, role, kinds, captions):
    """Nominate the existing caption layout without admitting a structure.

    Every original label cell must still have its complete, unchanged prefixed
    reading. A missing drawing is a separate retained association failure.
    Unknown, bare, conflicting or incomplete cells cannot hide column sources.
    """
    if not {"label", "drawing"}.issubset(kinds) or any(
        kind not in {"label", "drawing"} for kind in kinds
    ):
        return False
    xs, ys = region["xs"], region["ys"]
    expected = {
        (xs[col], ys[row], xs[col + 1], ys[row + 1])
        for row, kind in enumerate(kinds)
        if kind == "label"
        for col in range(len(xs) - 1)
    }
    if not isinstance(captions, (list, tuple)) or len(captions) != len(expected):
        return False
    represented = set()
    for item in captions:
        if (
            not isinstance(item, Mapping)
            or type(item.get("page")) is not int
            or item["page"] != page_no
            or item.get("caption_role") != role
            or item.get("review") is not False
            or item.get("bare") is not False
            or not isinstance(item.get("label"), str)
            or not item["label"]
        ):
            return False
        ownership = {"kind": "ruled_caption", "caption_role": role}
        windows = caption_windows(
            {
                "bbox": item.get("bbox"),
                "reading_bbox": item.get("bbox"),
                "observations": item.get("observations"),
                "ownership": ownership,
            }
        )
        if windows is None:
            return False
        cell = windows[0]
        if (
            cell not in expected
            or cell in represented
            or not confirmed_caption_readings(
                item["label"], item["observations"], ownership, page_no, cell
            )
        ):
            return False
        represented.add(cell)
    return bool(expected) and represented == expected
