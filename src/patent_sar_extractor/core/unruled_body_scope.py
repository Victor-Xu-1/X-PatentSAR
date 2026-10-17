"""Original post-header context and complete page-candidate scope, without OCR."""

from .activity_context_geometry import valid_box
from .source_cell_tokens import cell_lines, cell_text
from .source_observations import project_source_observation
from .source_section_roles import heading_members, section_body_boundary
from .source_table_markers import (
    TABLE_CAPTION_START,
    TABLE_MARKER,
    table_marker_identity,
)
from .source_window_chunks import validate_source_window, window_source_tokens
from .structure_table_headers import structure_column_pairs, structure_header_role
from .unruled_scope import scope_axes, scope_headers
from .unruled_structure_headers import header_groups


def body_context_window(scope):
    _xs, ys = scope_axes(scope)
    return [0, ys[1], *scope["page_size"]]


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
        raise ValueError("Malformed original unruled page-diagram inventory")


def _boundary_identity(parts, window):
    text = cell_text(parts, window)
    marker = TABLE_MARKER.match(text) if TABLE_CAPTION_START.match(text) else None
    if marker:
        return "table", table_marker_identity(marker.group()).casefold()
    heading = section_body_boundary(text)
    if heading:
        return (
            "section",
            heading["role"],
            heading["label_kind"],
            tuple(heading_members(heading)),
        )
    groups = header_groups(parts)
    if 2 <= len(groups) <= 64 and structure_column_pairs([g["text"] for g in groups]):
        return "columns", tuple(structure_header_role(g["text"]) for g in groups)
    return None


def _proved_boundary(chunks, window, expected):
    """Every nonempty qualified original lane must name the same boundary."""
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
        if parts and _boundary_identity(parts, window) != expected:
            return False
        if not native and not parts:
            return False
    return True


def original_body_bottom(scope, chunks, diagrams):
    window = body_context_window(scope)
    validate_source_window(chunks, window)
    validate_page_diagrams(diagrams, scope["page_size"])
    tokens = window_source_tokens(chunks, window)
    for line in cell_lines(tokens, window):
        top, bottom = min(p["bbox"][1] for p in line), max(p["bbox"][3] for p in line)
        bounds = [0, top, window[2], bottom]
        identity = _boundary_identity(line, bounds)
        if (
            identity is None
            or top <= window[1]
            or any(min(bottom, d["bbox"][3]) > max(top, d["bbox"][1]) for d in diagrams)
            or not _proved_boundary(chunks, bounds, identity)
        ):
            continue
        return max(window[1], top - 4) if identity[0] == "columns" else top
    return window[3]


def body_diagrams(scope, bottom, diagrams):
    xs, ys = scope_axes(scope)
    pairs = structure_column_pairs(scope_headers(scope))
    return [
        d
        for d in diagrams
        if d["bbox"][3] > ys[1]
        and d["bbox"][1] < bottom
        and any(
            min(d["bbox"][2], xs[s + 1]) > max(d["bbox"][0], xs[s]) for _, s in pairs
        )
    ]
