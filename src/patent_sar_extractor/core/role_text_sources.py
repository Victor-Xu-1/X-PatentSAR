"""Explicit original grid-role owners, not recursive search of arbitrary JSON."""

from itertools import pairwise

from patent_sar_extractor.contracts import CHARACTERIZATION_ROLE_SCHEMA_VERSION

from .activity_grid_roles import MAX_ROLE_ROW_HEIGHT, MAX_ROLE_TEXT_ROWS
from .cell_text_scope import scoped_height, text_scope
from .role_grid_windows import MAX_ROLE_GRID_CELLS, role_grid_shape
from .source_evidence_identity import proof_id
from .text_ocr.cell_proof import has_auxiliary_text, valid_auxiliary_cell
from .text_ocr.source_inventory import MAX_SOURCE_CELLS


def _region_scopes(region):
    if not isinstance(region, dict):
        raise TypeError("Malformed original role-text region")
    page_no = region.get("page_no")
    yield page_no, region.get("role_scope")
    fragments = region.get("row_fragments", [])
    if not isinstance(fragments, list) or len(fragments) > 2:
        raise ValueError("Malformed original open-row source inventory")
    for fragment in fragments:
        if not isinstance(fragment, dict):
            raise TypeError("Malformed original open-row source owner")
        cells = fragment.get("source_cells")
        if cells is not None:
            yield page_no, cells


def _role_scopes(payload):
    sections = payload.get("source_sections", [])
    observations = payload.get("source_role_observations", {})
    if not isinstance(sections, list) or not isinstance(observations, dict):
        raise TypeError("Malformed original role-text owners")
    for section in sections:
        if not isinstance(section, dict):
            raise TypeError("Malformed original role-text section")
        if section.get("role") == "characterization_region":
            yield from _region_scopes(section["source_region"])
    coverage = payload.get("coverage")
    if coverage is not None and not isinstance(coverage, dict):
        raise TypeError("Malformed original role-text coverage owner")
    if isinstance(coverage, dict):
        regions = coverage.get("regions", [])
        if not isinstance(regions, list) or any(
            not isinstance(region, dict) for region in regions
        ):
            raise ValueError("Malformed original role-text coverage")
        for region in regions:
            if "role_scope" in region:
                yield from _region_scopes(region)
    for observation in observations.values():
        if not isinstance(observation, dict):
            raise TypeError("Malformed original role-text diagnostic")
        cells = observation.get("source_cells")
        if cells is not None:
            if (
                type(observation.get("version")) is not int
                or observation["version"] != 1
            ):
                raise ValueError("Unknown original role-text diagnostic owner")
            yield observation.get("page_no"), cells


def _framed_cell(scope, view_index, cell_index, cell):
    if "rendered_frames" not in scope:
        return cell
    frames = scope["rendered_frames"]
    if not isinstance(frames, list):
        raise TypeError("Malformed original role-text frame inventory")
    if cell.get("method") == "native_cell":
        if frames:
            raise ValueError("Native original role cell has optical frames")
        return cell
    if (
        len(frames) != len(scope["observations"])
        or not isinstance(frames[view_index], list)
        or len(frames[view_index]) != len(scope["observations"][view_index]["cells"])
    ):
        raise ValueError("Incomplete original role-text frame inventory")
    frame = frames[view_index][cell_index]
    if "source_frame" in cell and cell["source_frame"] != frame:
        raise ValueError("Original role-text source frames disagree")
    return {**cell, "source_frame": frame}


def role_text_cells(payload):
    """Accepted/rejected owners keep every native, ordinary and auxiliary cell.

    This inventories source only. It never grants a characterization role or
    suppresses an unresolved observation. The shared auxiliary inventory owns
    model/request/paired-view verification. This same physical source inventory
    deduplicates owners but never merges different pages, bounds or DPI views.
    """
    seen = set()
    for page_no, scope in _role_scopes(payload):
        if (
            not isinstance(scope, dict)
            or role_grid_shape(scope.get("xs"), scope.get("ys")) is None
        ):
            raise ValueError("Malformed original role-text grid scope")
        if type(page_no) is not int or not 1 <= page_no <= 20000:
            raise ValueError("Missing original role-text page ownership")
        xs, ys = scope["xs"], scope["ys"]
        x_cells, y_cells = set(pairwise(xs)), set(pairwise(ys))
        views = scope.get("observations")
        if not isinstance(views, list) or len(views) > 2:
            raise ValueError("Malformed original role-text observations")
        for view_index, view in enumerate(views):
            cells = view.get("cells") if isinstance(view, dict) else None
            method = view.get("method") if isinstance(view, dict) else None
            if (
                method not in ("native_cells", "cell_ocr_400dpi", "cell_ocr_600dpi")
                or not isinstance(cells, list)
                or len(cells) > MAX_ROLE_GRID_CELLS
            ):
                raise ValueError("Malformed original role-text cell inventory")
            for cell_index, cell in enumerate(cells):
                if not isinstance(cell, dict):
                    raise TypeError("Malformed original role-text cell")
                if cell.get("method") != (
                    "native_cell" if method == "native_cells" else method
                ):
                    raise ValueError(
                        "Original role-text method differs from its source view"
                    )
                box = cell.get("bbox")
                if (
                    not isinstance(box, list)
                    or len(box) != 4
                    or any(
                        type(v) not in {int, float} or not 0 <= v <= 100000 for v in box
                    )
                    or (box[0], box[2]) not in x_cells
                    or (box[1], box[3]) not in y_cells
                ):
                    raise ValueError("Original text leaves its original role cell")
                cell = _framed_cell(scope, view_index, cell_index, cell)
                if (
                    scope.get("version") == CHARACTERIZATION_ROLE_SCHEMA_VERSION
                    and method != "native_cells"
                ):
                    if cell.get("text_scope") != text_scope(
                        MAX_ROLE_TEXT_ROWS, MAX_ROLE_ROW_HEIGHT
                    ):
                        raise ValueError(
                            "Missing or changed original role typography scope"
                        )
                    scoped_height(
                        cell,
                        maximum_row_height=MAX_ROLE_ROW_HEIGHT,
                        maximum_rows=MAX_ROLE_TEXT_ROWS,
                    )
                if has_auxiliary_text(cell):
                    if not valid_auxiliary_cell(cell, cell.get("render_dpi")):
                        raise ValueError("Unproved auxiliary original role-text cell")
                    carrier = {
                        "status": "auxiliary_text_observations",
                        "packet": cell["auxiliary_text"],
                    }
                else:
                    carrier = {"status": "original_role_cell", "cell": cell}
                key = page_no, proof_id(carrier)
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > MAX_SOURCE_CELLS:
                    raise ValueError(
                        "Original role-text inventory exceeds its source bound"
                    )
                yield page_no, cell
