"""Original native line order and shared physical row presentation, no OCR."""

from .source_cell_tokens import cell_text
from .source_observations import MAXIMUM_TOKENS


def _bounds(tokens):
    return [
        min(token["bbox"][0] for token in tokens),
        min(token["bbox"][1] for token in tokens),
        max(token["bbox"][2] for token in tokens),
        max(token["bbox"][3] for token in tokens),
    ]


def _window(tokens):
    return {
        "text": " ".join(token["text"] for token in tokens),
        "bbox": _bounds(tokens),
    }


def _overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def native_page_lines(layout):
    """Nominate complete overlapping original lines, never trim their boundaries.

    Native line metrics can overlap inside one original text block. Observing
    each as a separate cell then retains its neighbour as a boundary witness.
    Coalesce only adjacent same-block overlaps whose full physical word order
    agrees with the original extraction order, within the existing cell budget.
    These are nominations only: all original/visibility/readback checks remain.
    """
    groups = {}
    for token in layout.native:
        groups.setdefault(tuple(token["line"]), []).append(token)
    output, pending, block, bounds = [], [], None, None

    def finish():
        if not pending:
            return
        tokens = [token for group in pending for token in group]
        if len(pending) > 1 and len(tokens) <= MAXIMUM_TOKENS:
            current = _window(tokens)
            if cell_text(tokens, current["bbox"]).split() == current["text"].split():
                output.append(current)
                return
        output.extend(_window(group) for group in pending)

    for key, group in groups.items():
        box = _bounds(group)
        if pending and (key[0] != block or not _overlap(box, bounds)):
            finish()
            pending = []
            bounds = None
        pending.append(group)
        block = key[0]
        bounds = (
            [
                min(bounds[0], box[0]),
                min(bounds[1], box[1]),
                max(bounds[2], box[2]),
                max(bounds[3], box[3]),
            ]
            if bounds is not None
            else box
        )
    finish()
    return output


def observed_page_text(source):
    if source["origin"] == "native":
        # Native order is an original fact; display rotation must not reverse
        # a native table row or exchange its identifier and measured value.
        return source["nomination_text"]
    tokens = [
        {
            "text": line["text"],
            "bbox": line["bbox"],
            "x": (line["bbox"][0] + line["bbox"][2]) / 2,
            "y": (line["bbox"][1] + line["bbox"][3]) / 2,
        }
        for line in source["lines"]
    ]
    return cell_text(tokens, [0, 0, *source["page_size"]])
