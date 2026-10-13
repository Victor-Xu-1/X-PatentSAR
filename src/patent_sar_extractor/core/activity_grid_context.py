"""Original cell matrices and local caption windows."""

from .activity_grid_cells import cell_text
from .activity_headers import TABLE_MARKER
from .source_table_markers import TABLE_CAPTION_START


def table_matrix(tokens: list[dict], region: dict) -> list[list[str]]:
    xs, ys = region["xs"], region["ys"]
    return [
        [
            cell_text(tokens, (xs[i], ys[j], xs[i + 1], ys[j + 1]))
            for i in range(len(xs) - 1)
        ]
        for j in range(len(ys) - 1)
    ]


def _prefix(tokens: list[dict], region: dict) -> str:
    top = region["ys"][0]
    selected = [t for t in tokens if max(0, top - 310) <= t["y"] < top]
    lines: dict[int, list[dict]] = {}
    for token in selected:
        lines.setdefault(round(token["y"] / 3), []).append(token)
    text = []
    for _, row in sorted(lines.items()):
        parts: list[list[dict]] = [[]]
        for token in sorted(row, key=lambda t: t["x"]):
            if parts[-1] and TABLE_CAPTION_START.match(token["text"]):
                parts.append([])
            parts[-1].append(token)
        for part in parts:
            line = " ".join(t["text"] for t in part)
            # Separate adjacent captions on the same printed line. A caption
            # to the right of this panel cannot relabel its experiment.
            if (
                TABLE_MARKER.search(line)
                and part[0].get("bbox", [part[0]["x"]])[0] > region["xs"][0] + 8
            ):
                continue
            text.append(line)
    return "\n".join(text)
