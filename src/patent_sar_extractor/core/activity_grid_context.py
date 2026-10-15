"""Original cell matrices and local caption windows."""

from .activity_caption_windows import prefix_parts
from .activity_grid_cells import cell_text


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
    return "\n".join(
        " ".join(token["text"] for token in part)
        for part in prefix_parts(tokens, region)
    )


def _suffix(tokens: list[dict], region: dict, regions: list[dict]) -> str:
    """Other physical grids are not prose; new titles outside them stop carry."""
    selected = [
        t
        for t in tokens
        if t["y"] > region["ys"][-1] + 1
        and not any(
            other["xs"][0] <= t["x"] < other["xs"][-1]
            and other["ys"][0] <= t["y"] < other["ys"][-1]
            for other in regions
        )
    ]
    lines = {}
    for token in selected:
        lines.setdefault(round(token["y"] / 3), []).append(token)
    return "\n".join(
        " ".join(t["text"] for t in sorted(row, key=lambda t: t["x"]))
        for _, row in sorted(lines.items())
    )
