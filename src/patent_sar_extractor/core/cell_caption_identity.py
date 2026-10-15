"""Pure original detector-conflict guard for complete physical caption reads."""

import math
import re
from collections.abc import Mapping
from itertools import combinations

from .compound_caption import prefixed_label
from .ocr_claims import qualified_observation_runs
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

    observed_runs = qualified_observation_runs(detection_parts)
    if observed_runs is None:
        return True
    runs = [tuple(part["text"] for _index, part in run) for run in observed_runs]
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
    numeric_indices = [
        index
        for run in observed_runs
        for index, part in run
        if any(char.isnumeric() for char in part["text"])
    ]
    overlapping = {
        index
        for first, second in combinations(numeric_indices, 2)
        if min(boxes[first][2], boxes[second][2])
        - max(boxes[first][0], boxes[second][0])
        > 1
        and min(boxes[first][3], boxes[second][3])
        - max(boxes[first][1], boxes[second][1])
        > 1
        for index in (first, second)
    }
    # Only the intersecting qualified numeric fragments lack independent ID
    # ownership. Weak/unrelated boxes cannot exempt another original claim.
    if any(
        index not in overlapping and identifier_fragments_conflict(part["text"], label)
        for run in observed_runs
        for index, part in run
    ):
        return True
    return any(
        not overlapping.intersection(index for index, _part in observed)
        and conflicts(" ".join(text))
        for observed, text in zip(observed_runs, runs, strict=True)
    )
