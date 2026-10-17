"""Exact registered physical parents and original gaps, replayed after saving."""

from collections import defaultdict

from .ruled_column_continuation import KIND, physical_continuation_roles
from .ruled_continuation_context import qualified_running_window
from .source_body_context import contained_source_diagrams
from .source_window_chunks import project_source_window, validate_source_overlap
from .structure_column_scopes import original_columns_fit_frame
from .unruled_body_scope import body_context_window, column_body_extent
from .unruled_continuation_titles import anchor_scope
from .unruled_scope import scope_roles


def _source_tail(source):
    frame = source.get("grid_axes")
    if frame is not None:
        return frame["ys"][-1]
    return max(
        [
            body_context_window(source["header_scope"])[1],
            *[d["bbox"][3] for d in source["diagrams"]],
            *[label["nomination"]["bbox"][3] for label in source["labels"]],
        ]
    )


def physical_parent_context_start(parent, scope):
    """Only the registered parent's own rows determine the original gap floor."""
    return (
        _source_tail(parent["source"]) if parent["page_no"] == scope["page_no"] else 0
    )


def _qualified_parent_gap(section, scope, diagrams, roles):
    source, grid = section["source"], scope["grid_axes"]
    prior, frame = source["header_scope"], source.get("grid_axes")
    extent = column_body_extent(source)
    same_page = section["page_no"] == scope["page_no"]
    tail = _source_tail(source)
    if same_page:
        if tail > grid["ys"][0] or extent["trusted_bottom"] < grid["ys"][0]:
            return False
        # No intervening grid or unowned chemical drawing can be jumped over.
        if any(
            observed != frame
            and observed["ys"][0] < grid["ys"][0]
            and observed["ys"][-1] > tail
            for observed in scope["page_grids"]
        ) or any(
            d["bbox"][1] < grid["ys"][0] and d["bbox"][3] > tail for d in diagrams
        ):
            return False
        window = [0, tail, prior["page_size"][0], grid["ys"][0]]
    else:
        if extent["trusted_bottom"] != prior["page_size"][1] or any(
            d["bbox"][1] < grid["ys"][0] for d in diagrams
        ):
            return False
        if frame is None:
            owned = source["diagrams"]
        else:
            owned = contained_source_diagrams(
                source["page_diagrams"],
                [frame["xs"][0], frame["ys"][0], frame["xs"][-1], tail],
            )
        if any(
            d["bbox"][1] >= body_context_window(prior)[1] and d not in owned
            for d in source["page_diagrams"]
        ):
            return False
        window = [0, tail, prior["page_size"][0], prior["page_size"][1]]
    chunks = (
        project_source_window(
            source["body_context"], body_context_window(prior), window
        )
        if window[1] < window[3]
        else []
    )
    return qualified_running_window(chunks, window, roles["xs"], roles["pairs"])


def eligible_physical_parents(sections, scope, diagrams):
    """No nearest-page/ID-order choice; every surviving parent must be unique."""
    grid, size, page = scope["grid_axes"], scope["page_size"], scope["page_no"]
    matches = []
    for section in sections:
        prior = section["source"]["header_scope"]
        if section["page_no"] not in {page - 1, page}:
            continue
        anchor, roles = anchor_scope(prior), scope_roles(prior)
        if (
            roles is None
            or anchor is None
            or prior["original_pdf_sha256"] != scope["original_pdf_sha256"]
            or prior["page_size"][0] != size[0]
            or not original_columns_fit_frame(anchor, grid["xs"])
            or not _qualified_parent_gap(section, scope, diagrams, roles)
        ):
            continue
        candidate = {
            **scope,
            "anchor_scope": anchor,
            "parent_region_id": section["region_id"],
            "parent_page_no": section["page_no"],
            "context_start": physical_parent_context_start(section, scope),
        }
        if physical_continuation_roles(candidate) is not None:
            matches.append(section)
    return matches


def validate_physical_links(sections):
    by_page = defaultdict(list)
    for section in sections:
        by_page[section["page_no"]].append(section)
    for section in sections:
        source, scope = section["source"], section["source"]["header_scope"]
        if scope.get("kind") != KIND:
            continue
        physical_continuation_roles(scope)
        if not scope["parent_region_id"]:
            continue  # Its unresolved-header finding remains mandatory.
        matches = eligible_physical_parents(
            [*by_page[scope["page_no"] - 1], *by_page[scope["page_no"]]],
            scope,
            source["page_diagrams"],
        )
        if len(matches) != 1 or matches[0]["region_id"] != scope["parent_region_id"]:
            raise ValueError(
                "Physical continuation has no unique registered original parent"
            )
        parent = matches[0]
        if scope["anchor_scope"] != anchor_scope(
            parent["source"]["header_scope"]
        ) or scope["context_start"] != physical_parent_context_start(parent, scope):
            raise ValueError("Physical continuation changed its original anchor or gap")
        leading = [0, 0, scope["page_size"][0], scope["grid_axes"]["ys"][1]]
        if parent["page_no"] == scope["page_no"]:
            validate_source_overlap(
                scope["leading_context"],
                leading,
                parent["source"]["body_context"],
                body_context_window(parent["source"]["header_scope"]),
            )
        # Prefix and complete body conserve the first real row on every replay.
        validate_source_overlap(
            scope["leading_context"],
            leading,
            source["body_context"],
            body_context_window(scope),
        )
