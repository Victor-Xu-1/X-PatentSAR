"""One ruled-caption ownership path, including split label/drawing page breaks."""

from dataclasses import dataclass, field

from .activity_context_geometry import MAX_TABLES, context_region, grid_axes, grid_box
from .activity_grid_context import _prefix
from .caption_boundary_context import observe_caption_tail
from .caption_grid_rows import caption_rows, numbered_header_nominee
from .caption_grid_rows import inside as _inside
from .caption_page_boundary import (
    CaptionGridCarry,
    adjacent_caption_grid,
    caption_boundary_proof,
    qualified_caption_carries,
)
from .caption_role_links import role_link
from .caption_role_observation import observe_caption_role
from .caption_role_proof import caption_role_status
from .source_table_markers import TABLE_MARKER
from .table_cells import read_cell
from .table_geometry import detect_ruled_table_regions, page_tokens


@dataclass
class CaptionGridResult:
    bindings: list[dict] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    labels: set[str] = field(default_factory=set)
    issues: list[dict] = field(default_factory=list)
    tokens: dict[int, list[dict]] = field(default_factory=dict)
    exclusions: list[dict] = field(default_factory=list)
    regions: dict[int, list[tuple]] = field(default_factory=dict)
    protected_structure_ids: set[str] = field(default_factory=set)
    roles: dict[tuple[int, tuple], dict] = field(default_factory=dict)


def bind_caption_grids(
    doc, by_page, boxes_by_page, pages, *, grids_for_page=None, tokens_for_page=None
):
    """A catalog direction is proved at its start and carried only adjacent grids.

    An unproved recognized catalog cannot fall back to nearest-caption matching.
    Cross-page proof retains both original page identities. No sequence fills IDs.
    """
    result = CaptionGridResult()
    grids_for_page = grids_for_page or (
        lambda page: detect_ruled_table_regions(page, dpi=240)
    )
    tokens_for_page = tokens_for_page or (
        lambda page: page_tokens(page, dpi=200, allow_tesseract=False)
    )
    carries = []
    catalog_boxes = result.regions

    def reject(item, reason):
        result.issues.append(
            {
                "cpd": item.get("label", ""),
                "page_no": item["page"],
                "reason": reason,
                "evidence": {
                    key: item[key]
                    for key in ("bbox", "observations", "structure_cell")
                    if key in item
                },
            }
        )

    def bind(item, page_no, cell, direction, boundary=None):
        boxes = boxes_by_page.get(page_no, [])
        owners = [
            s
            for s, box in zip(by_page.get(page_no, []), boxes_by_page.get(page_no, []))
            if _inside(box, cell)
        ]
        rivals = [
            box
            for box in boxes
            if box
            and min(box[2], cell[2]) - max(box[0], cell[0]) > 2
            and min(box[3], cell[3]) - max(box[1], cell[1]) > 2
        ]
        if (
            len(owners) != 1
            or len(rivals) != 1
            or any(box is None for box in boxes)
            or item["review"]
        ):
            reject(
                {**item, "structure_cell": list(cell)},
                "unread_or_conflicting_caption"
                if item["review"]
                else "missing_caption_structure"
                if not owners
                else "ambiguous_caption_structure",
            )
            return
        result.bindings.append(
            {
                "label": item["label"],
                "structure": owners[0],
                "label_bbox": item["bbox"],
                "label_page_no": item["page"],
                "observations": item["observations"],
                "ownership": {
                    "kind": "ruled_caption",
                    "direction": direction,
                    "label_cell": list(item["bbox"]),
                    "structure_cell": list(cell),
                    "structure_page_no": page_no,
                    **(
                        {"caption_role": item["caption_role"]}
                        if item.get("caption_role")
                        else {}
                    ),
                    **({"identifier_form": "bare"} if item.get("bare") else {}),
                    **({"page_boundary": boundary} if boundary is not None else {}),
                },
            }
        )

    for page_no in sorted(set(pages)):
        page = doc[page_no - 1]
        observed_grids = grids_for_page(page)
        if len(observed_grids) > MAX_TABLES:
            raise ValueError("Original caption page exceeds its frame resource bound")
        grids = sorted(observed_grids, key=lambda g: (g["ys"][0], g["xs"][0]))
        tokens = tokens_for_page(page) if grids else []
        if grids:
            result.tokens[page_no] = tokens
        prior_frames = qualified_caption_carries(carries)
        next_carries, consumed = [], set()
        for region in grids:
            xs, ys = region["xs"], region["ys"]
            if numbered_header_nominee(region, tokens):
                continue
            caption = _prefix(
                tokens, context_region(region, [grid_box(g) for g in grids])
            )
            new_table = bool(TABLE_MARKER.search(caption))
            role = observe_caption_role(page, region, grids, tokens)
            matches = [
                (index, prior)
                for index, prior in prior_frames
                if index not in consumed
                and adjacent_caption_grid(prior, page_no, region, role, new_table)
            ]
            carry_index, carry = matches[0] if len(matches) == 1 else (None, None)
            adjacent = carry is not None
            if (
                role is not None
                and role["role"] == "unknown"
                and adjacent
                and carry.role
            ):
                inherited = {
                    **role,
                    "role": carry.role["role"],
                    "table_key": carry.role["table_key"],
                    "continuation": role_link(
                        carry.role, carry.axes, region, carry.direction, carry.tail
                    ),
                }
                if caption_role_status(inherited, page_no, grid_box(region)):
                    role = inherited
            # The original grid frame is verified once here. Constructed child
            # cells retain the same role; formal consumers replay every owner.
            role_status = caption_role_status(role, page_no, grid_box(region))
            if role_status == "nonfinal":
                result.roles[(page_no, tuple(grid_box(region)))] = role
                if carry_index is not None:
                    consumed.add(carry_index)
                    for item in carry.pending:
                        reject(item, "unproved_cross_page_caption")
                result.pages.add(page_no)
                result.exclusions.append(
                    {
                        "role": "nonfinal_caption_catalog",
                        "status": "observed_nonfinal_caption_catalog",
                        "page_no": page_no,
                        "bbox": grid_box(region),
                        "caption_role": role,
                        "structure_ids": [
                            str(s.get("id") or "")
                            for s, box in zip(
                                by_page.get(page_no, []), boxes_by_page.get(page_no, [])
                            )
                            if _inside(box, grid_box(region))
                        ],
                    }
                )
                catalog_boxes.setdefault(page_no, []).append(tuple(grid_box(region)))
                result.protected_structure_ids.update(
                    result.exclusions[-1]["structure_ids"]
                )
                next_carries.append(
                    CaptionGridCarry(
                        page_no,
                        grid_axes(region),
                        None,
                        role,
                        tail=observe_caption_tail(
                            page,
                            role,
                            grids,
                            tokens,
                            by_page.get(page_no, []),
                            boxes_by_page.get(page_no, []),
                        ),
                    )
                )
                continue
            rows, kinds = caption_rows(
                region, tokens, boxes_by_page.get(page_no, []), role
            )
            bridge_only = bool(
                adjacent
                and kinds
                and (
                    carry.direction == "above"
                    and carry.pending
                    and kinds[0] == "drawing"
                    or carry.direction == "below"
                    and carry.trailing_drawing
                    and kinds[0] == "label"
                )
            )
            if (not any(rows) or "drawing" not in kinds) and not bridge_only:
                continue
            if carry_index is not None:
                consumed.add(carry_index)
            if role_status == "compound":
                result.roles[(page_no, tuple(grid_box(region)))] = role
            result.pages.add(page_no)
            catalog_boxes.setdefault(page_no, []).append((xs[0], ys[0], xs[-1], ys[-1]))
            result.protected_structure_ids.update(
                str(s.get("id") or "")
                for s, box in zip(
                    by_page.get(page_no, []), boxes_by_page.get(page_no, [])
                )
                if _inside(box, grid_box(region))
            )
            direction = (
                carry.direction
                if adjacent
                else (
                    "above"
                    if kinds[0] == "label" and new_table
                    else "below"
                    if kinds[0] == "drawing"
                    and new_table
                    and (kinds[-1] == "label" or len(kinds) > 1 and kinds[1] == "label")
                    else None
                )
            )
            boundary = (
                caption_boundary_proof(carry.role, role, direction, carry.tail)
                if adjacent
                else None
            )
            for item in carry.pending if carry else ():
                if boundary and direction == "above" and kinds[0] == "drawing":
                    col = item["column"]
                    bind(
                        item,
                        page_no,
                        (xs[col], ys[0], xs[col + 1], ys[1]),
                        direction,
                        boundary,
                    )
                else:
                    reject(item, "unproved_cross_page_caption")
            pending = []
            for row, labels in enumerate(rows):
                if kinds[row] != "label":
                    continue
                observed = {col: (label, bare) for col, label, _, bare in labels}
                labels = [
                    (
                        col,
                        observed.get(col, ("", False))[0],
                        (xs[col], ys[row], xs[col + 1], ys[row + 1]),
                        observed.get(col, ("", False))[1],
                    )
                    for col in range(len(xs) - 1)
                ]
                for col, label, cell, bare in labels:
                    reading = read_cell(
                        page,
                        cell,
                        tokens,
                        "id" if bare else "label",
                        bool(page.get_text("words")),
                    )
                    resolved = label or reading.value
                    if resolved:
                        result.labels.add(resolved)
                    item = {
                        "label": resolved,
                        "page": page_no,
                        "bbox": cell,
                        "column": col,
                        "review": reading.needs_review
                        or not resolved
                        or bool(label and reading.value != label)
                        or role_status in {"mixed", "conflict"},
                        "observations": reading.observations,
                        "bare": bare,
                        "caption_role": role,
                    }
                    if bare and role_status != "compound":
                        item["review"] = True
                    target = row + 1 if direction == "above" else row - 1
                    if direction == "above" and target == len(rows):
                        pending.append(item)
                    elif direction == "below" and row == 0 and bridge_only and boundary:
                        old = carry.axes
                        bind(
                            item,
                            carry.page_no,
                            (
                                old["xs"][col],
                                old["ys"][-2],
                                old["xs"][col + 1],
                                old["ys"][-1],
                            ),
                            direction,
                            boundary,
                        )
                    elif (
                        direction is None
                        or not 0 <= target < len(rows)
                        or kinds[target] != "drawing"
                    ):
                        reject(item, "unproved_caption_direction")
                    else:
                        bind(
                            item,
                            page_no,
                            (xs[col], ys[target], xs[col + 1], ys[target + 1]),
                            direction,
                        )
            trailing = kinds[-1] == "drawing"
            tail = observe_caption_tail(
                page,
                role,
                grids,
                tokens,
                by_page.get(page_no, []),
                boxes_by_page.get(page_no, []),
            )
            next_carries.append(
                CaptionGridCarry(
                    page_no,
                    grid_axes(region),
                    direction,
                    role,
                    trailing,
                    tail,
                    tuple(pending),
                )
            )
        for index, prior in enumerate(carries):
            if index not in consumed:
                for item in prior.pending:
                    reject(item, "unproved_cross_page_caption")
        carries = next_carries
    for carry in carries:
        for item in carry.pending:
            reject(item, "unproved_cross_page_caption")
    bound = {str(b["structure"].get("id") or "") for b in result.bindings} | {
        identity
        for section in result.exclusions
        for identity in section["structure_ids"]
    }
    for page_no, grids in catalog_boxes.items():
        for structure, box in zip(
            by_page.get(page_no, []), boxes_by_page.get(page_no, [])
        ):
            if str(structure.get("id") or "") not in bound and any(
                _inside(box, cell) for cell in grids
            ):
                result.issues.append(
                    {
                        "cpd": "",
                        "page_no": page_no,
                        "reason": "unbound_caption_structure",
                        "structure_id": structure.get("id"),
                    }
                )
    return result
