"""Pure original detector-conflict guard for complete physical caption reads."""

import math
import re
from collections.abc import Mapping
from itertools import combinations

from .compound_caption import prefixed_label
from .ocr_claims import qualified_text_runs
from .printed_identifiers import LABEL_PREFIX, identifier_fragments_conflict
from .source_section_roles import nonfinal_original_label


def refined_caption_conflicts(label, parts, detection_parts):
    if parts is not None and not isinstance(parts, (list, tuple)):
        return True
    if not any(
        isinstance(part, Mapping) and part.get("method") == "complete_line_recognition"
        for part in parts or ()
    ):
        return False
    if (
        not isinstance(detection_parts, (list, tuple))
        or not 1 <= len(detection_parts) <= 32
        or any(
            not isinstance(part, Mapping)
            or not isinstance(part.get("text"), str)
            or len(part["text"]) > 512
            for part in detection_parts
        )
    ):
        return True

    def conflicts(text):
        detected = prefixed_label(text)
        return bool(
            nonfinal_original_label(text)
            or detected
            and detected != label
            or not detected
            and re.match(LABEL_PREFIX, text, re.IGNORECASE)
            and any(char.isnumeric() for char in text)
            and identifier_fragments_conflict(text, label, caption=True)
        )

    runs = qualified_text_runs(detection_parts)
    if runs is None:
        return True
    if any(conflicts(text) for run in runs for text in run):
        return True
    # Intersecting detector fragments do not constitute another complete literal
    # caption: 13/37 is a physical overlap, not two independent compound IDs.
    boxes = []
    try:
        for part in detection_parts:
            points = part["bbox"]
            if (
                not isinstance(points, (list, tuple))
                or len(points) != 4
                or any(
                    not isinstance(point, (list, tuple))
                    or len(point) != 2
                    or any(
                        type(v) not in {int, float}
                        or not math.isfinite(v)
                        or not 0 <= v <= 8_000_000
                        for v in point
                    )
                    for point in points
                )
            ):
                return True
            boxes.append(
                (
                    min(p[0] for p in points),
                    min(p[1] for p in points),
                    max(p[0] for p in points),
                    max(p[1] for p in points),
                )
            )
            if boxes[-1][0] >= boxes[-1][2] or boxes[-1][1] >= boxes[-1][3]:
                return True
    except (KeyError, TypeError, ValueError, IndexError):
        return True
    overlaps = any(
        min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1
        for a, b in combinations(boxes, 2)
    )
    return not overlaps and any(
        conflicts(" ".join(run)) or identifier_fragments_conflict(" ".join(run), label)
        for run in runs
    )
