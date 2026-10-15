"""Original cell matrices and local caption windows."""

from .activity_context_geometry import context_floor
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


def prefix_parts(tokens: list[dict], region: dict) -> list[list[dict]]:
    """Retain the original token parts under the one caption-window policy."""
    top = region["ys"][0]
    floor = (
        context_floor(region["context_geometry"])
        if "context_geometry" in region
        else max(0, top - 310)
    )
    floor = max(floor, region.get("context_start", floor))
    selected = [t for t in tokens if floor <= t["y"] < top]
    lines: dict[int, list[dict]] = {}
    for token in selected:
        lines.setdefault(round(token["y"] / 3), []).append(token)
    output = []
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
            output.append(part)
    return output


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
