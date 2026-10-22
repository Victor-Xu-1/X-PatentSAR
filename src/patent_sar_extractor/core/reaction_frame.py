"""Recognize only the actual opaque stroke of a proved enclosing source cell."""


def original_frame_path(path, page, frame):
    if frame is None:
        return False
    items, color = path.get("items", []), path.get("color")
    if not (
        path.get("type") == "s"
        and path.get("stroke_opacity") == 1
        and isinstance(color, tuple)
        and color
        and max(color) <= 0.45
        and 0 < path.get("width", 0) <= 4
        and path.get("dashes") == "[] 0"
        and len(items) == 1
        and items[0][0] == "re"
    ):
        return False
    original = items[0][1] * page.rotation_matrix
    # The sole grid observer measures centres on the 240dpi original rendering.
    # At most one such pixel, not a general geometry/ink exclusion tolerance.
    return all(abs(a - b) <= 72 / 240 for a, b in zip(original, frame, strict=True))
