"""One physical-column header observation adapter, no assay/value inference."""

import math
from dataclasses import dataclass
from itertools import pairwise

from .activity_grid_cells import crosses_cell
from .activity_header_identity import detector_header_conflict
from .cell_ocr_observation import observe_cell
from .page_ocr_cache import get_ocr_engine
from .source_geometry import native_cell_text
from .table_cells import cell_image


@dataclass(frozen=True)
class HeaderColumns:
    matrix: list[list[str]]
    columns: tuple[dict, ...]
    verified: tuple[bool, ...]


def observe_header_columns(
    page, region, limit: int, dpi: int, tokens=()
) -> HeaderColumns:
    """Read only the declared header band; preserve every line/crop observation.

    OCR identity and confidence are supplied by the existing shared engine.
    Blank/low-confidence/cross-boundary cells do not supply admission evidence.
    """
    xs, ys = region["xs"], region["ys"]
    if (
        type(dpi) is not int
        or dpi not in {400, 600}
        or type(limit) is not int
        or not 1 <= limit < len(ys)
        or not 2 <= len(xs) <= 65
        or any(
            type(v) not in {int, float} or not math.isfinite(v)
            for edges in (xs, ys)
            for v in edges
        )
        or any(b <= a for edges in (xs, ys) for a, b in pairwise(edges))
        or any(
            max(0, b - a - 3) * max(0, ys[limit] - ys[0] - 2.4) * (dpi / 72) ** 2
            > 8_000_000
            for a, b in pairwise(xs)
        )
    ):
        raise ValueError("Original header column exceeds bounded rendering scope")
    engine = get_ocr_engine()
    if not engine or engine[0] != "rapidocr":
        raise RuntimeError("Original column headers require the coordinate OCR engine")
    columns, headers, verified = [], [], []
    for column in range(len(xs) - 1):
        bounds = (xs[column], ys[0], xs[column + 1], ys[limit])
        reading = observe_cell(
            cell_image(page, bounds, dpi),
            "header",
            dpi,
            engine[1],
            lambda text, _kind: text.strip(),
        )
        crossing = crosses_cell(list(tokens), bounds)
        conflict = bool(
            reading.physical_header_lines
            and detector_header_conflict(reading.detection_parts, reading.raw_text)
        )
        columns.append(
            {
                **reading.evidence(dpi, bounds),
                "native_text": native_cell_text(tokens, bounds),
                "physical_column": column,
                "crosses_boundary": crossing,
                **(
                    {"detector_conflict": conflict}
                    if reading.physical_header_lines is not None
                    else {}
                ),
            }
        )
        headers.append(reading.raw_text)
        verified.append(bool(reading.value) and not crossing and not conflict)
    # The complete band has one source per column. Keep its original physical
    # row boundary instead of interpreting joined header lines as data rows.
    matrix = [[""] * len(headers) for _ in range(limit - 1)] + [headers]
    return HeaderColumns(matrix, tuple(columns), tuple(verified))
