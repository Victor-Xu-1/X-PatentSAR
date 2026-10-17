"""Bounded physical continuation windows; raw rows never join identifier digits."""

from .heading_source_geometry import (
    HEADING_PADDING,
    MAX_HEADING_HEIGHT,
    MAX_HEADING_ROWS,
)
from .source_section_roles import heading_assay_tail, heading_list_hint, section_heading


def heading_line_windows(lines):
    if len(lines) > 50000:
        raise ValueError("Original heading line inventory exceeds its bound")
    output, index = [], 0
    while index < len(lines):
        first = lines[index]
        parts = [first]
        declaration = section_heading(first["text"])
        hinted = heading_list_hint(first["text"])
        if declaration or hinted:
            while index + len(parts) < len(lines):
                following = lines[index + len(parts)]
                last, box = parts[-1], first["bbox"]
                next_box = following["bbox"]
                gap = next_box[1] - last["bbox"][3]
                height = max(
                    last["bbox"][3] - last["bbox"][1], next_box[3] - next_box[1]
                )
                continues = (
                    hinted
                    and declaration is None
                    or (
                        declaration
                        and declaration["label_kind"] in {"example", "实施例"}
                        and heading_assay_tail(following["text"])
                    )
                )
                combined = "\n".join(
                    [*(part["text"] for part in parts), following["text"]]
                )
                continued = section_heading(combined)
                if not continued and not heading_list_hint(combined):
                    break
                if not (
                    continues
                    and first["source"] == following["source"]
                    and -2 <= gap <= height / 2
                    and box[0] - 2 <= next_box[0] <= box[2]
                    and next_box[1] > last["bbox"][1]
                    and next_box[3] - box[1]
                    <= MAX_HEADING_HEIGHT - (HEADING_PADDING[3] - HEADING_PADDING[1])
                ):
                    break
                if len(parts) >= MAX_HEADING_ROWS:
                    raise ValueError("Original heading continuation exceeds eight rows")
                parts.append(following)
                declaration = continued
            if len(parts) > 1:
                first = {
                    **first,
                    "text": "\n".join(part["text"] for part in parts),
                    "bbox": [
                        min(part["bbox"][0] for part in parts),
                        min(part["bbox"][1] for part in parts),
                        max(part["bbox"][2] for part in parts),
                        max(part["bbox"][3] for part in parts),
                    ],
                    "y1": max(part["bbox"][3] for part in parts),
                    "heading_rows": [
                        {
                            "text": part["text"],
                            "bbox": list(part["bbox"]),
                            "source": part["source"],
                        }
                        for part in parts
                    ],
                }
        output.append(first)
        index += len(parts)
    return output
