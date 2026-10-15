"""One bounded confidence qualification for retained detector text claims."""

from collections.abc import Mapping

from .cell_ocr_scores import confidence_value


def qualified_text_runs(parts):
    """Unqualified words stay evidence; never join across their missing roles.

    Malformed confidence/shape is not a neutral low-confidence reading. Return
    None so callers keep the source unresolved. No text is repaired or removed
    from the caller's original observation packet.
    """
    if not isinstance(parts, (list, tuple)) or len(parts) > 32:
        return None
    runs, current = [], []
    for part in parts:
        if (
            not isinstance(part, Mapping)
            or not isinstance(part.get("text"), str)
            or len(part["text"]) > 4096
            or part.get("confidence_valid", True) is not True
            or confidence_value(part.get("confidence")) is None
        ):
            return None
        if part["confidence"] >= 0.85:
            current.append(part["text"])
        elif current:
            runs.append(tuple(current))
            current = []
    if current:
        runs.append(tuple(current))
    return tuple(runs)
