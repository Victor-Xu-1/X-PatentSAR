"""One physical-column header observation adapter, no assay/value inference."""

from dataclasses import dataclass

from .activity_grid_cells import crosses_cell
from .cell_ocr_observation import observe_cell
from .page_ocr_cache import get_ocr_engine
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
    engine = get_ocr_engine()
    if not engine or engine[0] != "rapidocr":
        raise RuntimeError("Original column headers require the coordinate OCR engine")
    xs, ys = region["xs"], region["ys"]
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
        columns.append(
            {
                **reading.evidence(dpi, bounds),
                "physical_column": column,
                "crosses_boundary": crossing,
            }
        )
        headers.append(reading.raw_text)
        verified.append(bool(reading.value) and not crossing)
    # The complete band has one source per column. Keep its original physical
    # row boundary instead of interpreting joined header lines as data rows.
    matrix = [[""] * len(headers) for _ in range(limit - 1)] + [headers]
    return HeaderColumns(matrix, tuple(columns), tuple(verified))
