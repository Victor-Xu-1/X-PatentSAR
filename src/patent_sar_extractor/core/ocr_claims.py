"""One bounded confidence qualification for retained detector text claims."""

from collections.abc import Mapping

from .cell_ocr_scores import confidence_value


def qualified_observation_runs(parts, *, maximum_parts=32):
    """Unqualified words stay evidence; never join across their missing roles.

    Malformed confidence/shape is not a neutral low-confidence reading. Return
    None so callers keep the source unresolved. No text is repaired or removed
    from the caller's original observation packet.
    """
    if (
        type(maximum_parts) is not int
        or maximum_parts not in {32, 512}
        or not isinstance(parts, (list, tuple))
        or len(parts) > maximum_parts
    ):
        return None
    runs, current = [], []
    for index, part in enumerate(parts):
        if (
            not isinstance(part, Mapping)
            or not isinstance(part.get("text"), str)
            or len(part["text"]) > 4096
            or part.get("confidence_valid", True) is not True
            or confidence_value(part.get("confidence")) is None
        ):
            return None
        if part["confidence"] >= 0.85:
            current.append((index, part))
        elif current:
            runs.append(tuple(current))
            current = []
    if current:
        runs.append(tuple(current))
    return tuple(runs)


def qualified_text_runs(parts, *, maximum_parts=32):
    """Text projection of the same qualified original observation inventory."""
    runs = qualified_observation_runs(parts, maximum_parts=maximum_parts)
    if runs is None:
        return None
    return tuple(tuple(part["text"] for _index, part in run) for run in runs)
