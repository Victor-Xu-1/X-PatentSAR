"""Exact registered parents of physical continuations, replayed after saving."""

from collections import defaultdict

from .ruled_column_continuation import KIND, physical_continuation_roles
from .ruled_continuation_context import qualified_running_window
from .source_body_context import contained_source_diagrams
from .source_window_chunks import project_source_window, validate_source_overlap
from .structure_column_scopes import original_columns_fit_frame
from .unruled_body_scope import body_context_window, column_body_extent
from .unruled_continuation_titles import anchor_scope
from .unruled_scope import scope_roles


def eligible_physical_parents(sections, scope, diagrams):
    """No nearest-page/ID-order choice; every surviving parent must be unique."""
    grid, size, page = scope["grid_axes"], scope["page_size"], scope["page_no"]
    if any(d["bbox"][1] < grid["ys"][0] for d in diagrams):
        return []
    matches = []
    for section in sections:
        source = section["source"]
        prior = source["header_scope"]
        if (
            section["page_no"] != page - 1
        ):  # Same-page frames require an explicit source boundary.
            continue
        anchor = anchor_scope(prior)
        roles = scope_roles(prior)
        if (
            roles is None
            or anchor is None
            or prior["original_pdf_sha256"] != scope["original_pdf_sha256"]
            or prior["page_size"][0] != size[0]
            or not original_columns_fit_frame(anchor, grid["xs"])
        ):
            continue
        extent = column_body_extent(source)
        if extent["trusted_bottom"] != prior["page_size"][1]:
            continue
        frame = source.get("grid_axes")
        if frame is None:
            tail = max(
                [
                    body_context_window(prior)[1],
                    *[d["bbox"][3] for d in source["diagrams"]],
                    *[label["nomination"]["bbox"][3] for label in source["labels"]],
                ]
            )
            owned = source["diagrams"]
        else:
            tail = frame["ys"][-1]
            owned = contained_source_diagrams(
                source["page_diagrams"],
                [frame["xs"][0], frame["ys"][0], frame["xs"][-1], tail],
            )
        if any(
            d["bbox"][1] >= body_context_window(prior)[1] and d not in owned
            for d in source["page_diagrams"]
        ):
            continue
        window = [0, tail, prior["page_size"][0], prior["page_size"][1]]
        chunks = (
            project_source_window(
                source["body_context"], body_context_window(prior), window
            )
            if tail < window[3]
            else []
        )
        if not qualified_running_window(chunks, window, roles["xs"], roles["pairs"]):
            continue
        candidate = {
            **scope,
            "anchor_scope": anchor,
            "parent_region_id": section["region_id"],
            "parent_page_no": section["page_no"],
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
            by_page[scope["page_no"] - 1], scope, source["page_diagrams"]
        )
        if len(matches) != 1 or matches[0]["region_id"] != scope["parent_region_id"]:
            raise ValueError(
                "Physical continuation has no unique registered original parent"
            )
        parent = matches[0]
        if scope["anchor_scope"] != anchor_scope(parent["source"]["header_scope"]):
            raise ValueError("Physical continuation changed its original column anchor")
        # The current root's prefix and complete body must be exact projections
        # where they meet; an empty prefix cannot erase the first real row.
        validate_source_overlap(
            scope["leading_context"],
            [0, 0, scope["page_size"][0], scope["grid_axes"]["ys"][1]],
            source["body_context"],
            body_context_window(scope),
        )
