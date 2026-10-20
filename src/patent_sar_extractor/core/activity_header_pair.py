"""Both original header views share one optional, unresolved-only auxiliary pass."""

from .activity_header_columns import HeaderColumns
from .cell_raster import original_reading_image
from .text_ocr.cell_capture import refine_text_pair
from .text_ocr.configuration import get_auxiliary_text_runtime


def observe_header_pair(page, region, limit, tokens, observer):
    pair = [observer(page, region, limit, dpi, tokens) for dpi in (400, 600)]
    if all(all(view.verified) for view in pair):
        return pair
    auxiliary = get_auxiliary_text_runtime()
    if auxiliary is None:
        return pair
    columns = [list(view.columns) for view in pair]
    verified = [list(view.verified) for view in pair]
    if len(columns[0]) != len(columns[1]):
        raise ValueError("Original header column count differs across source views")
    for index, primaries in enumerate(zip(*columns)):
        if all(v[index] for v in verified) or any(
            p.get("crosses_boundary") or p.get("detector_conflict") for p in primaries
        ):
            continue
        if primaries[0].get("bbox") != primaries[1].get("bbox"):
            continue
        images = tuple(
            original_reading_image(page, p["bbox"], dpi, p)
            for p, dpi in zip(primaries, (400, 600))
        )
        attempts = []
        changed = refine_text_pair(images, primaries, auxiliary, evidence_sink=attempts)
        if changed is not None:
            for view, reading in enumerate(changed):
                columns[view][index] = {**reading, "detector_conflict": False}
                verified[view][index] = True
        elif attempts:
            for view, primary in enumerate(primaries):
                columns[view][index] = {**primary, "auxiliary_attempt": attempts[0]}
    return [
        HeaderColumns(
            [[""] * len(view_columns) for _ in range(limit - 1)]
            + [[c["raw_text"] for c in view_columns]],
            tuple(view_columns),
            tuple(view_verified),
        )
        for view_columns, view_verified in zip(columns, verified)
    ]
