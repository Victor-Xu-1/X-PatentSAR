"""Original body-boundary facts shared by capture and saved-source consumers.

No rendering, model, table matching, inference, cache or result writer. Suspect
boundaries retain the full inventory while ending positively trusted ownership.
"""

from .activity_context_geometry import valid_box
from .source_cell_tokens import cell_lines, cell_text
from .source_observations import project_source_observation
from .source_section_roles import heading_members, section_body_boundary
from .source_table_markers import (
    TABLE_CAPTION_START,
    caption_table_marker,
    table_marker_identity,
)
from .source_window_chunks import validate_source_window, window_source_tokens
from .structure_table_headers import (
    header_groups,
    structure_column_pairs,
    structure_header_role,
)


def validate_page_diagrams(diagrams, page_size):
    if (
        not isinstance(diagrams, list)
        or len(diagrams) > 25000
        or any(
            not isinstance(d, dict)
            or set(d) != {"id", "bbox"}
            or not isinstance(d["id"], str)
            or not 1 <= len(d["id"]) <= 256
            or not isinstance(d["bbox"], list)
            or not valid_box(d["bbox"])
            or not 0 <= d["bbox"][0] < d["bbox"][2] <= page_size[0]
            or not 0 <= d["bbox"][1] < d["bbox"][3] <= page_size[1]
            for d in diagrams
        )
        or len({d["id"] for d in diagrams}) != len(diagrams)
    ):
        raise ValueError("Malformed original page-diagram inventory")


def contained_source_diagrams(diagrams, bounds):
    """Select observed boxes inside one proved frame, never reserve a page."""
    if not valid_box(bounds):
        raise ValueError("Invalid original diagram-ownership frame")
    return [
        diagram
        for diagram in diagrams
        if bounds[0] <= diagram["bbox"][0] < diagram["bbox"][2] <= bounds[2]
        and bounds[1] <= diagram["bbox"][1] < diagram["bbox"][3] <= bounds[3]
    ]


def box_inside_drawing(box, diagrams):
    """Whole original text containment, not vertical overlap or proximity."""
    return any(
        d["bbox"][0] <= box[0] < box[2] <= d["bbox"][2]
        and d["bbox"][1] <= box[1] < box[3] <= d["bbox"][3]
        for d in diagrams
    )


def _boundary_identity(parts, window, *, column_boundaries):
    text = cell_text(parts, window)
    marker = caption_table_marker(text)
    if TABLE_CAPTION_START.match(text):
        return (
            "table",
            table_marker_identity(marker.group()).casefold()
            if marker
            else "raw:" + text.casefold(),
        )
    heading = section_body_boundary(text)
    if heading:
        return (
            "section",
            heading["role"],
            heading["label_kind"],
            tuple(heading_members(heading)),
        )
    groups = header_groups(parts) if column_boundaries else []
    if 2 <= len(groups) <= 64 and structure_column_pairs([g["text"] for g in groups]):
        return "columns", tuple(structure_header_role(g["text"]) for g in groups)
    return None


def _proved_boundary(chunks, window, expected, *, column_boundaries):
    """Every nonempty original lane must qualify and name the same boundary."""
    for native in (False, True):
        parts = []
        for chunk in chunks:
            clip = [
                window[0],
                max(window[1], chunk["bbox"][1]),
                window[2],
                min(window[3], chunk["bbox"][3]),
            ]
            if not valid_box(clip):
                continue
            source = (
                next(p for p in chunk["sources"] if p["origin"] == "native")
                if native
                else chunk["sources"][0]
            )
            observed = project_source_observation(source, clip)
            if observed["text"].strip() and observed["status"] != "qualified":
                return False
            parts.extend(observed["tokens"])
        if (
            parts
            and _boundary_identity(parts, window, column_boundaries=column_boundaries)
            != expected
        ):
            return False
        if not native and not parts:
            return False
    return True


def _boundary_lines(tokens, window):
    """Nominate literal titles that overlap a neighbouring baseline.

    These are original-token subsets, not corrected text. The ordinary complete
    source projection still independently proves or refuses every nominated
    window; a geometric subset never supplies its own acceptance evidence.
    """
    for line in cell_lines(tokens, window):
        yield line
        bands = {}
        for part in line:
            bands.setdefault((part["bbox"][1], part["bbox"][3]), []).append(part)
        if len(bands) > 1:
            yield from bands.values()


def original_context_extent(chunks, window, diagrams, *, column_boundaries=True):
    """A doubtful boundary never trims facts or extends a nonfinal exclusion."""
    validate_source_window(chunks, window)
    events, seen = [], set()
    lanes = (False,) if all(len(c["sources"]) == 1 for c in chunks) else (False, True)
    for native in lanes:
        tokens = window_source_tokens(chunks, window, native=native)
        for line in _boundary_lines(tokens, window):
            top = min(p["bbox"][1] for p in line)
            bottom = max(p["bbox"][3] for p in line)
            bounds = [window[0], top, window[2], bottom]
            identity = _boundary_identity(
                line, bounds, column_boundaries=column_boundaries
            )
            if (
                identity is None
                or top <= window[1]
                or (tuple(bounds), identity) in seen
            ):
                continue
            # A table reference wholly inside an observed drawing is not a
            # page-level table title. Keep its original tokens, but do not let
            # the annotation split or taint the surrounding source inventory.
            line_box = [
                min(p["bbox"][0] for p in line),
                top,
                max(p["bbox"][2] for p in line),
                bottom,
            ]
            if identity[0] == "table" and box_inside_drawing(line_box, diagrams):
                continue
            if len(events) >= 25000:
                raise ValueError("Original body-boundary inventory exceeds its bound")
            seen.add((tuple(bounds), identity))
            overlaps_diagram = any(
                min(bottom, d["bbox"][3]) > max(top, d["bbox"][1]) for d in diagrams
            )
            proved = not overlaps_diagram and _proved_boundary(
                chunks, bounds, identity, column_boundaries=column_boundaries
            )
            cut = max(window[1], top - 4) if identity[0] == "columns" else top
            events.append(
                {"bbox": bounds, "identity": identity, "proved": proved, "cut": cut}
            )
    bottom = min([window[3], *(e["cut"] for e in events if e["proved"])])
    unproved = [e for e in events if not e["proved"] and e["bbox"][1] < bottom]
    unproved.sort(key=lambda e: (e["bbox"][1], e["bbox"][0], e["identity"]))
    return {
        "body_bottom": bottom,
        "trusted_bottom": min([bottom, *(e["cut"] for e in unproved)]),
        "unproved_boundaries": [
            {"bbox": e["bbox"], "identity": e["identity"]} for e in unproved
        ],
    }
