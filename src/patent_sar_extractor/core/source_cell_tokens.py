"""One physical cell-token selection and literal multiline layout authority."""


def cell_tokens(tokens, bounds):
    x0, y0, x1, y1 = bounds
    return [t for t in tokens if x0 <= t["x"] < x1 and y0 <= t["y"] < y1]


def cell_lines(tokens, bounds):
    """Preserve printed lines; overlap joins baseline/subscript fragments only."""
    lines = []
    for token in sorted(cell_tokens(tokens, bounds), key=lambda t: (t["y"], t["x"])):
        box = token.get("bbox")
        for line in reversed(lines):
            anchor = line[0]
            other = anchor.get("bbox")
            if box and other:
                overlap = min(box[3], other[3]) - max(box[1], other[1])
                height = min(box[3] - box[1], other[3] - other[1])
                same_line = height > 0 and overlap >= 0.3 * height
            else:
                same_line = abs(token["y"] - anchor["y"]) <= 3
            if same_line:
                line.append(token)
                break
        else:
            lines.append([token])
    return [sorted(line, key=lambda t: t["x"]) for line in lines]


def cell_text(tokens, bounds):
    return "\n".join(
        " ".join(t["text"] for t in line) for line in cell_lines(tokens, bounds)
    )


def crosses_cell(tokens, bounds):
    x0, y0, x1, y1 = bounds
    return any(
        (box := token.get("bbox"))
        and (box[0] < x0 - 1 or box[1] < y0 - 1 or box[2] > x1 + 1 or box[3] > y1 + 1)
        for token in cell_tokens(tokens, bounds)
    )
