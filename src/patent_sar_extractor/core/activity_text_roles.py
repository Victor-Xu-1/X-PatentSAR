"""Negative text claims linked to an existing complete physical role proof.

This does not classify a table or select a winning read. It only links each
literal DPI view to its same physical spectral data cell, never an ID/header.
"""

from patent_sar_extractor.contracts import CHARACTERIZATION_ROLE_SCHEMA_VERSION

from .activity_grid_role_proof import valid_role_scope
from .activity_grid_roles import characterization_conflict
from .cell_frame_proof import inside_box
from .source_cell_claims import native_witness


def characterization_cells(regions):
    """Validate each complete owner once per caller/page, not once per line."""
    owners = {}
    for region in regions:
        proof = region.get("role_scope")
        if not (
            region.get("kind") == "grid"
            and region.get("status") == "non_activity"
            and region.get("reason") == "observed_characterization"
            and isinstance(proof, dict)
            and type(proof.get("version")) is int
            and proof["version"] == CHARACTERIZATION_ROLE_SCHEMA_VERSION
            and valid_role_scope(region)
            and region.get("grid_axes") == {"xs": proof["xs"], "ys": proof["ys"]}
        ):
            continue
        views = proof["observations"]
        if [view["method"] for view in views] != ["cell_ocr_400dpi", "cell_ocr_600dpi"]:
            continue  # Native lines still use the existing exact literal proof.
        width = len(proof["xs"]) - 1
        roles = proof["roles"]
        owners[region["region_id"]] = [
            tuple(view["cells"][row * width + column] for view in views)
            for row in range(roles["data_start"], len(proof["ys"]) - 1)
            for column, role in enumerate(roles["columns"])
            if role in {"nmr", "mass", "characterization"}
        ]
    return owners


def _contains(original, claim):
    words, selected = original.split(), claim.split()
    return bool(selected) and any(
        words[index : index + len(selected)] == selected
        for index in range(len(words) - len(selected) + 1)
    )


def characterization_line(line, cells):
    """Both independent views must link literally to ONE identical data cell.

    Outer page/line source quality and actual original replay are still required
    by the caller. Even a known NMR role never owns a new scientific condition,
    a weak/unknown read, a crossing line or a conflicting original witness.
    """
    readings = [
        reading for reading in line["observations"] if not native_witness(reading)
    ]
    if [reading.get("method") for reading in readings] != [
        "cell_ocr_400dpi",
        "cell_ocr_600dpi",
    ] or any(
        characterization_conflict(text)
        for text in (
            line["nomination"],
            line["text"],
            *[reading["text"] for reading in readings],
        )
    ):
        return False
    matches = [
        pair
        for pair in cells
        if inside_box(line["bbox"], pair[0]["bbox"])
        and all(
            cell["bbox"] == pair[0]["bbox"]
            and cell["method"] == reading["method"]
            and _contains(cell["text"], reading["text"])
            for cell, reading in zip(pair, readings, strict=True)
        )
    ]
    return len(matches) == 1
