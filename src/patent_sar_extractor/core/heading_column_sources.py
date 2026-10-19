"""Original registered column witnesses, never a guessed page split or ID order."""

from .source_body_context import contained_source_diagrams
from .source_evidence_identity import proof_id
from .structure_column_anchors import column_anchor_diagrams, column_anchor_roles
from .unruled_body_scope import column_body_extent
from .unruled_scope import scope_axes, scope_body_top
from .unruled_structure_layout import region_plan

COLUMN_SOURCE_ROLES = {"structure_column_anchor", "unruled_structure_region"}


def checked_column_source(section, page, original_sha, expected):
    """Recheck one registered original region without projecting a heading lane."""
    if (
        not isinstance(section, dict)
        or set(section) != {"role", "status", "page_no", "region_id", "source"}
        or section["role"] not in COLUMN_SOURCE_ROLES
        or type(section["page_no"]) is not int
        or section["page_no"] != page["page_no"]
    ):
        raise ValueError("Malformed original heading column source")
    source = section["source"]
    if not isinstance(source, dict) or section["region_id"] != proof_id(source):
        raise ValueError("Changed original heading column identity")
    if section["role"] == "structure_column_anchor":
        roles = column_anchor_roles(source)
        diagrams = column_anchor_diagrams(source)
        xs = source["grid_axes"]["xs"]
        top = scope_body_top(source["header_scope"])
        bottom = min(
            source["grid_axes"]["ys"][-1],
            column_body_extent(source)["trusted_bottom"],
        )
    else:
        roles, pairs, _ = region_plan(source)
        diagrams = (
            [source["diagrams"][i] for _, i in pairs]
            if roles is not None and roles["role"] == "compound"
            else source["diagrams"]
        )
        xs, _ = scope_axes(source["header_scope"])
        top = scope_body_top(source["header_scope"])
        bottom = column_body_extent(source)["trusted_bottom"]
    header = source["header_scope"]
    if (
        header["original_pdf_sha256"] != original_sha
        or header["page_no"] != page["page_no"]
        or header["page_size"] != page["page_size"]
        or section["status"] != source["status"]
        or {s["id"]: s["bbox"] for s in source["page_diagrams"]} != expected
    ):
        raise ValueError("Heading column has foreign or incomplete original inventory")
    return roles, [xs[0], top, xs[-1], bottom], diagrams


def independent_columns(sections, page, heading):
    """Replay the same original role/body policies used by the source catalogue.

    Only a positively trusted column active alongside this heading can exclude
    its own contained diagrams. All raw candidates remain in the scope packet.
    No column is projected onto another page or beyond its original body extent.
    """
    if not isinstance(sections, list) or len(sections) > 25000:
        raise ValueError("Malformed original heading column inventory")
    expected = {s["structure_id"]: s["bbox"] for s in page["structures"]}
    columns, known = [], set()
    box = heading["nomination"]["bbox"]
    for section in sections:
        if (
            not isinstance(section, dict)
            or set(section) != {"role", "status", "page_no", "region_id", "source"}
            or section["role"] not in COLUMN_SOURCE_ROLES
            or type(section["page_no"]) is not int
            or section["page_no"] != page["page_no"]
            or section["region_id"] in known
        ):
            raise ValueError("Malformed original heading column source")
        known.add(section["region_id"])
        roles, bounds, diagrams = checked_column_source(
            section, page, heading["original_pdf_sha256"], expected
        )
        left, top, right, bottom = bounds
        if (
            roles is None
            or roles["role"] not in {"compound", "nonfinal"}
            or not top < bottom
            or not (box[2] <= left or right <= box[0])
        ):
            continue
        contained = contained_source_diagrams(diagrams, bounds)
        if contained:
            active = top <= box[1] < box[3] <= bottom
            columns.append(
                {
                    "bbox": bounds,
                    "active": active,
                    "diagrams": contained if active else [],
                }
            )
    return columns


def foreign_column_line(box, columns):
    """Ignore only contained foreign lines; a closing edge stays ambiguous.

    A procedure at another column's closing edge must not manufacture a complete
    singleton window for this heading. Unproved later/global flow is not guessed.
    """
    for column in columns:
        if not column["active"]:
            continue
        if any(
            b[0] <= box[0] < box[2] <= b[2] and b[1] <= box[1] < box[3] <= b[3]
            for b in column.get("caption_boxes", ())
        ):
            return "contained"
        left, top, right, bottom = column["bbox"]
        if not left <= box[0] < box[2] <= right:
            continue
        if top <= box[1] < box[3] <= bottom:
            return "contained"
        if box[1] <= bottom <= box[3]:
            return "closing"
    return ""


def ambiguous_column_flow(box, heading, columns):
    """Closed historical columns veto a guessed lane; they never claim new ink."""
    return any(
        not column["active"]
        and heading["nomination"]["bbox"][1] >= column["bbox"][3]
        and column["bbox"][0] <= box[0] < box[2] <= column["bbox"][2]
        for column in columns
    )
