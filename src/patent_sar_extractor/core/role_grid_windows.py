"""One bounded closed-grid inventory; work units never stand for whole coverage."""

from itertools import pairwise

from patent_sar_extractor.contracts import CHARACTERIZATION_ROLE_SCHEMA_VERSION

MAX_ROLE_CELLS = 96
MAX_ROLE_GRID_CELLS = 4096
MAX_ROLE_COLUMNS = 64


def role_grid_shape(xs, ys, *, maximum=MAX_ROLE_GRID_CELLS):
    for edges in (xs, ys):
        if (
            not isinstance(edges, list)
            or not 2 <= len(edges) <= maximum + 1
            or any(
                type(value) not in {int, float} or not 0 <= value <= 100000
                for value in edges
            )
            or any(right <= left for left, right in pairwise(edges))
        ):
            return None
    rows, columns = len(ys) - 1, len(xs) - 1
    if columns > MAX_ROLE_COLUMNS or rows * columns > maximum:
        return None
    return rows, columns


def role_work_windows(xs, ys):
    """Every complete physical row exactly once, keeping all of its columns."""
    shape = role_grid_shape(xs, ys)
    if shape is None:
        return None
    rows, columns = shape
    step = MAX_ROLE_CELLS // columns
    return [[start, min(start + step, rows)] for start in range(0, rows, step)]


def valid_role_windows(proof):
    version = proof.get("version")
    if type(version) is not int or version not in {
        1,
        2,
        CHARACTERIZATION_ROLE_SCHEMA_VERSION,
    }:
        return False
    maximum = MAX_ROLE_CELLS if version == 1 else MAX_ROLE_GRID_CELLS
    if role_grid_shape(proof.get("xs"), proof.get("ys"), maximum=maximum) is None:
        return False
    if version == 1:
        return "work_windows" not in proof
    windows = proof.get("work_windows")
    return bool(
        isinstance(windows, list)
        and all(
            isinstance(window, list)
            and len(window) == 2
            and all(type(index) is int for index in window)
            for window in windows
        )
        and windows == role_work_windows(proof["xs"], proof["ys"])
    )
