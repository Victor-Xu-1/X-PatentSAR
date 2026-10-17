"""Construct original physical cells only after source/column registration."""

from collections import defaultdict
from itertools import pairwise

from .numbered_structure_models import NumberedTableCell, NumberedTableIssue
from .numbered_structure_pairs import _box, _overlaps
from .source_cell_tokens import cell_text
from .structure_catalogs import catalog_for_scope
from .structure_column_anchors import ANCHOR_ROLE, column_anchor_roles
from .unruled_body_scope import column_body_extent


def _unused_pair(page, label_bounds, structure_bounds, structures, page_index):
    """Both original cells must be blank, with no rival segment evidence."""
    if not callable(getattr(page, "get_pixmap", None)):
        return False
    for structure in structures:
        if structure.get("page_no") != page_index + 1:
            continue
        box = _box([structure.get(key) for key in ("x0", "y0", "x1", "y1")])
        if box is None or _overlaps(box, structure_bounds):
            return False
    from .table_cells import cell_image

    for bounds in (label_bounds, structure_bounds):
        image = cell_image(page, bounds, 150)
        # Fixed tiny noise allowance; never erase a small molecule in a large cell.
        if int((image.min(axis=2) < 200).sum()) > 4:
            return False
    return True


def observe_ruled_cells(doc, structures, sections, tokens_for_page, cell_reader):
    """One producer feeds the existing matcher; no carried or repaired headers."""
    by_page = defaultdict(list)
    for section in sections:
        by_page[section["page_no"] - 1].append(section)
    cells, issues = [], []
    for page_index, page_sections in sorted(by_page.items()):
        page, tokens = doc[page_index], tokens_for_page(doc[page_index])
        native = bool(page.get_text("words"))
        anchors = sorted(
            (s for s in page_sections if s["role"] == ANCHOR_ROLE),
            key=lambda s: s["source"]["grid_axes"]["ys"][0],
        )
        for grid_index, section in enumerate(anchors):
            source = section["source"]
            roles = column_anchor_roles(source)
            if roles is None:
                issues.append(
                    NumberedTableIssue(page_index, "", "unproved_original_ruled_header")
                )
                continue
            if roles["role"] == "nonfinal":
                continue
            scope, grid = source["header_scope"], source["grid_axes"]
            xs, ys = grid["xs"], grid["ys"]
            start = int(scope.get("kind") == "original_ruled_columns")
            trusted = column_body_extent(source)["trusted_bottom"]
            catalog = catalog_for_scope(scope)
            for row, (top, bottom) in enumerate(pairwise(ys), start=0):
                if row < start:
                    continue
                if bottom > trusted:
                    issues.append(
                        NumberedTableIssue(
                            page_index, "", "original_ruled_row_after_source_boundary"
                        )
                    )
                    continue
                for pair, (identifier, structure) in enumerate(roles["pairs"]):
                    label_bounds = (xs[identifier], top, xs[identifier + 1], bottom)
                    structure_bounds = (xs[structure], top, xs[structure + 1], bottom)
                    if not cell_text(tokens, label_bounds).strip() and _unused_pair(
                        page, label_bounds, structure_bounds, structures, page_index
                    ):
                        continue
                    reading = cell_reader(page, label_bounds, tokens, "id", native)
                    cells.append(
                        NumberedTableCell(
                            page_index,
                            grid_index,
                            row,
                            pair,
                            str(reading.value),
                            label_bounds,
                            structure_bounds,
                            tuple(dict(o) for o in reading.observations),
                            not reading.needs_review,
                            catalog,
                            {
                                "grid_xs": xs,
                                "headers": roles["headers"],
                                "identifier_column": identifier,
                                "structure_column": structure,
                                "source_anchor_id": section["region_id"],
                                "header_scope": scope,
                                "grid_axes": grid,
                            },
                        )
                    )
    return cells, issues
