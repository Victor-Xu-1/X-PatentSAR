"""Prepare original physical cells for the existing single numbered matcher."""

from collections import defaultdict
from dataclasses import replace
from itertools import pairwise

from .numbered_structure_models import NumberedTableIssue
from .structure_column_anchors import ANCHOR_ROLE, column_anchor_roles
from .unruled_body_scope import column_body_extent


def prepare_ruled_cells(cells, sections):
    """Only independently observed original roles enter the existing cell matcher."""
    by_row = defaultdict(list)
    for section in sections:
        if section["role"] == ANCHOR_ROLE:
            roles = column_anchor_roles(section["source"])
            scope, grid = (
                section["source"]["header_scope"],
                section["source"]["grid_axes"],
            )
            start = int(scope.get("kind") == "original_ruled_columns")
            trusted = column_body_extent(section["source"])["trusted_bottom"]
            for top, bottom in pairwise(grid["ys"][start:]):
                by_row[(section["page_no"], tuple(grid["xs"]), top, bottom)].append(
                    (section, roles, trusted)
                )
    prepared, issues = [], []
    for cell in cells:
        matches = (
            by_row.get(
                (
                    cell.page_index + 1,
                    tuple(cell.column_ownership["grid_xs"]),
                    cell.label_bounds[1],
                    cell.label_bounds[3],
                ),
                [],
            )
            if cell.column_ownership
            else []
        )
        if len(matches) != 1 or matches[0][1] is None:
            issues.append(
                NumberedTableIssue(
                    cell.page_index, cell.label, "unproved_original_ruled_header"
                )
            )
            continue
        section, roles, trusted = matches[0]
        scope = section["source"]["header_scope"]
        if cell.label_bounds[3] > trusted:
            issues.append(
                NumberedTableIssue(
                    cell.page_index,
                    cell.label,
                    "original_ruled_row_after_source_boundary",
                )
            )
            continue
        if roles["role"] == "nonfinal":
            continue
        prepared.append(
            replace(
                cell,
                column_ownership={
                    **cell.column_ownership,
                    "headers": roles["headers"],
                    "source_anchor_id": section["region_id"],
                    "header_scope": scope,
                    "grid_axes": section["source"]["grid_axes"],
                },
            )
        )
    return prepared, issues
