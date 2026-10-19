"""Explicit original grid-role owners, not recursive search of arbitrary JSON."""

from itertools import pairwise

from .role_grid_windows import MAX_ROLE_GRID_CELLS, role_grid_shape
from .text_ocr.cell_proof import has_auxiliary_text


def _role_scopes(payload):
    sections = payload.get("source_sections", [])
    observations = payload.get("source_role_observations", {})
    if not isinstance(sections, list) or not isinstance(observations, dict):
        raise TypeError("Malformed original role-text owners")
    for section in sections:
        if not isinstance(section, dict):
            raise TypeError("Malformed original role-text section")
        if section.get("role") == "characterization_region":
            region = section["source_region"]
            if not isinstance(region, dict):
                raise ValueError("Malformed original role-text region")
            yield region.get("page_no"), region.get("role_scope")
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
                yield region.get("page_no"), region["role_scope"]
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


def role_text_cells(payload):
    """Both accepted and rejected owners keep every selected auxiliary cell.

    This inventories source only. It never grants a characterization role or
    suppresses an unresolved observation. The shared auxiliary inventory owns
    model/request/paired-view verification, deduplication and its resource bound.
    """
    for page_no, scope in _role_scopes(payload):
        if (
            not isinstance(scope, dict)
            or role_grid_shape(scope.get("xs"), scope.get("ys")) is None
        ):
            raise ValueError("Malformed original role-text grid scope")
        xs, ys = scope["xs"], scope["ys"]
        x_cells, y_cells = set(pairwise(xs)), set(pairwise(ys))
        views = scope.get("observations")
        if not isinstance(views, list) or len(views) > 2:
            raise ValueError("Malformed original role-text observations")
        for view in views:
            cells = view.get("cells") if isinstance(view, dict) else None
            if not isinstance(cells, list) or len(cells) > MAX_ROLE_GRID_CELLS:
                raise ValueError("Malformed original role-text cell inventory")
            for cell in cells:
                if not isinstance(cell, dict):
                    raise TypeError("Malformed original role-text cell")
                if not has_auxiliary_text(cell):
                    continue
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
                    raise ValueError("Auxiliary text leaves its original role cell")
                yield page_no, cell
