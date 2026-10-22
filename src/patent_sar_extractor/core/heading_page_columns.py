"""Later-page catalogue witnesses, never a projected heading/page-half lane."""

from itertools import pairwise

from .heading_column_captions import column_caption_boxes, valid_caption_frames
from .heading_column_sources import checked_column_source
from .heading_source_proof import proved_heading_declaration
from .numbered_structure_models import NumberedTableCell
from .numbered_structure_pairs import pair_numbered_table_cells
from .ruled_structure_proof import validate_ruled_source_reference
from .source_section_roles import heading_members
from .structure_catalogs import catalog_for_scope
from .unruled_scope import scope_axes
from .unruled_structure_layout import region_plan


def capture_column_cells(cells, section):
    """Retain existing observations; this does not reread, pair or qualify them."""
    return [
        {
            "row": cell.row,
            "pair": cell.pair,
            "value": cell.label,
            "observations": list(cell.observations),
            "needs_review": not cell.label_confirmed,
        }
        for cell in cells
        if cell.column_ownership is not None
        and cell.column_ownership.get("source_anchor_id") == section["region_id"]
    ]


def _ruled_pairs(section, page, roles, bounds, readings):
    source, cells = section["source"], []
    scope, grid = source["header_scope"], source["grid_axes"]
    xs, ys = grid["xs"], grid["ys"]
    first = int(scope.get("kind") == "original_ruled_columns")
    expected = {
        (row, pair)
        for row, (_, bottom) in enumerate(pairwise(ys))
        if row >= first and bottom <= bounds[3]
        for pair in range(len(roles["pairs"]))
    }
    seen = set()
    for raw in readings:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"row", "pair", "value", "observations", "needs_review"}
            or type(raw["row"]) is not int
            or type(raw["pair"]) is not int
            or not isinstance(raw["value"], str)
            or len(raw["value"]) > 128
            or type(raw["needs_review"]) is not bool
            or not isinstance(raw["observations"], list)
            or not 1 <= len(raw["observations"]) <= 4
        ):
            raise ValueError("Malformed original later-column cell observation")
        row, pair = raw["row"], raw["pair"]
        if (row, pair) in seen or (row, pair) not in expected:
            raise ValueError("Changed original later-column row population")
        seen.add((row, pair))
        identifier, structure = roles["pairs"][pair]
        cells.append(
            NumberedTableCell(
                page["page_no"] - 1,
                0,
                row,
                pair,
                raw["value"],
                (xs[identifier], ys[row], xs[identifier + 1], ys[row + 1]),
                (xs[structure], ys[row], xs[structure + 1], ys[row + 1]),
                tuple(raw["observations"]),
                not raw["needs_review"],
                catalog_for_scope(scope),
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
    if not expected or seen != expected:
        return None  # Missing/blank/unread cells cannot gain exclusion authority.
    structures = [
        {
            "id": item["structure_id"],
            "page_no": page["page_no"],
            **dict(zip(("x0", "y0", "x1", "y1"), item["bbox"], strict=True)),
        }
        for item in page["structures"]
    ]
    result = pair_numbered_table_cells(cells, structures)
    if result.issues or len(result.bindings) != len(cells):
        return None
    for item in result.bindings:
        validate_ruled_source_reference(
            section,
            {
                "cpd": "Compound " + item.label,
                "page_no": page["page_no"],
                "structure_id": item.structure["id"],
                **{
                    ("struct_" + key): item.structure[key]
                    for key in ("x0", "y0", "x1", "y1")
                },
                "source_pdf_sha256": scope["original_pdf_sha256"],
                "numbered_table_cell_evidence": item.evidence(),
            },
            trusted_bottom=bounds[3],
        )
    return [(item.label, str(item.structure["id"])) for item in result.bindings]


def later_page_columns(witnesses, page, heading):
    """Known independent table rows may not suppress an own/unknown diagram."""
    if not isinstance(witnesses, list) or len(witnesses) > 25000:
        raise ValueError("Malformed original later-column collection")
    declaration = proved_heading_declaration(heading)
    if declaration is None:
        raise ValueError("Later-page source has no proved heading declaration")
    own = set(heading_members(declaration))
    expected = {item["structure_id"]: item["bbox"] for item in page["structures"]}
    columns, known = [], set()
    for witness in witnesses:
        if not isinstance(witness, dict) or set(witness) != {
            "section",
            "cells",
            "caption_frames",
        }:
            raise ValueError("Malformed original later-column witness")
        section, readings = witness["section"], witness["cells"]
        roles, bounds, diagrams = checked_column_source(
            section, page, heading["original_pdf_sha256"], expected
        )
        if (
            section["region_id"] in known
            or not isinstance(readings, list)
            or len(readings) > 25000
        ):
            raise ValueError(
                "Duplicate or excessive original later-column observations"
            )
        known.add(section["region_id"])
        scope = section["source"]["header_scope"]
        if (
            roles is None
            or roles["role"] != "compound"
            or not bounds[1] < bounds[3]
            or scope.get("kind")
            not in (
                None,
                "original_ruled_columns",
                "continued_ruled_columns",
                "continued_unruled_columns",
            )
        ):
            continue
        captions = column_caption_boxes(scope, page)
        if not valid_caption_frames(
            witness["caption_frames"], captions, page["page_size"]
        ):
            raise ValueError("Missing or changed local catalogue title pixel frames")
        if not captions and scope.get("kind") in (None, "original_ruled_columns"):
            continue
        # A proved continuation can own its complete current rows without a
        # fresh local title. Its ancestor is not projected as a page boundary;
        # the same row/identity/diagram proof below still decides exclusion.
        if section["role"] == "structure_column_anchor":
            pairs = _ruled_pairs(section, page, roles, bounds, readings)
        else:
            if readings:
                raise ValueError(
                    "Logical columns cannot contain physical row witnesses"
                )
            _, assigned, issues = region_plan(section["source"])
            region = section["source"]
            pairs = (
                None
                if issues
                else [
                    (region["labels"][i]["value"], region["diagrams"][j]["id"])
                    for i, j in assigned
                ]
            )
        if (
            not pairs
            or own.intersection(label for label, _ in pairs)
            or {sid for _, sid in pairs} != {item["id"] for item in diagrams}
        ):
            continue
        _, ys = scope_axes(scope)
        columns.append(
            {
                "bbox": [bounds[0], ys[0], bounds[2], bounds[3]],
                "active": True,
                "diagrams": diagrams,
                "caption_boxes": captions,
                "source_id": section["region_id"],
            }
        )
    return columns
