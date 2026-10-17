"""Replay adjacent original source links without recursive parent payloads."""

from collections import defaultdict

from .activity_context_geometry import valid_box
from .printed_identifiers import identifier_key
from .source_cell_tokens import cell_lines, cell_text
from .source_window_chunks import (
    validate_source_overlap,
    validate_source_window,
    window_source_tokens,
)
from .unruled_body_scope import body_context_window
from .unruled_continuation_titles import (
    anchor_scope,
    continuation_identity,
    continuation_nominees,
    qualified_table_key,
)
from .unruled_scope import scope_axes, scope_roles


def eligible_parents(sections, page_no, key, nomination):
    same_page, previous_page = [], []
    for section in sections:
        region = section["source"]
        scope = region["header_scope"]
        if qualified_table_key(scope) != key or scope_roles(scope) is None:
            continue
        if (
            scope["page_no"] == page_no
            and region["body_bottom"] == nomination["bbox"][1]
            and scope_axes(scope)[1][1] < nomination["bbox"][1]
        ):
            same_page.append(section)
        elif (
            scope["page_no"] == page_no - 1
            and region["body_bottom"] == scope["page_size"][1]
        ):
            previous_page.append(section)
    return same_page if same_page else previous_page


def compatible_diagram_scope(parent, scope, diagrams):
    prior = parent["source"]
    if parent["page_no"] == scope["page_no"]:
        return diagrams == prior["page_diagrams"]
    return not any(d["bbox"][1] < scope_axes(scope)[1][1] for d in diagrams)


def validate_continuation_links(sections):
    by_page = defaultdict(list)
    for section in sections:
        by_page[section["page_no"]].append(section)
    for section in sections:
        region, scope = section["source"], section["source"]["header_scope"]
        if (
            scope.get("kind") != "continued_unruled_columns"
            or not scope["parent_region_id"]
        ):
            continue
        matches = eligible_parents(
            [*by_page[scope["page_no"] - 1], *by_page[scope["page_no"]]],
            scope["page_no"],
            qualified_table_key(scope),
            scope["caption"]["nomination"],
        )
        if len(matches) != 1 or matches[0]["region_id"] != scope["parent_region_id"]:
            raise ValueError("Unproved original unruled continuation parent link")
        previous = matches[0]
        parent = previous["source"]["header_scope"]
        if (
            previous["page_no"] != scope["parent_page_no"]
            or anchor_scope(parent) != scope["anchor_scope"]
        ):
            raise ValueError(
                "Continuation columns differ from the registered original anchor"
            )
        if not compatible_diagram_scope(previous, scope, region["page_diagrams"]):
            raise ValueError("Original continuation skips an earlier page diagram")
        if previous["page_no"] == scope["page_no"]:
            validate_source_overlap(
                scope["leading_context"],
                [0, 0, scope["page_size"][0], scope["caption"]["bbox"][3]],
                previous["source"]["body_context"],
                body_context_window(parent),
            )


def repeated_header_covers(scope, diagrams, nomination):
    if scope.get("kind") == "continued_unruled_columns" or scope_roles(scope) is None:
        return False
    sources = scope["context_sources"]
    if not sources:
        return False
    chunks = [{"bbox": sources[0]["bbox"], "sources": sources}]
    validate_source_window(chunks, sources[0]["bbox"])
    nom_box = nomination["bbox"]
    if not sources[0]["bbox"][1] <= nom_box[1] < nom_box[3] <= sources[0]["bbox"][3]:
        return False
    tokens = window_source_tokens(chunks, sources[0]["bbox"])
    if nomination not in continuation_nominees(
        tokens,
        scope["page_size"],
        native_tokens=window_source_tokens(chunks, sources[0]["bbox"], native=True),
    ):
        return False
    xs, ys = scope_axes(scope)
    gap = [0, nom_box[3], scope["page_size"][0], ys[0]]
    if not valid_box(gap):
        return False
    if any(min(gap[3], d["bbox"][3]) > max(gap[1], d["bbox"][1]) for d in diagrams):
        return False
    for native in (False, True):
        parts = window_source_tokens(chunks, gap, native=native)
        for identifier, _structure in scope_roles(scope)["pairs"]:
            box = [xs[identifier], gap[1], xs[identifier + 1], gap[3]]
            if any(
                identifier_key(cell_text(line, box), wrapped=True, terminal_period=True)
                for line in cell_lines(parts, box)
            ):
                return False
    return True


def uncovered_continuation_issues(sections):
    """A declared later part stays visible even when no interpretation succeeded."""
    observed, registered, by_page = {}, set(), defaultdict(list)
    for section in sections:
        region, scope = section["source"], section["source"]["header_scope"]
        by_page[scope["page_no"]].append(region)
        if scope.get("kind") == "continued_unruled_columns":
            nomination = scope["caption"]["nomination"]
            registered.add(
                (
                    scope["page_no"],
                    tuple(nomination["bbox"]),
                    continuation_identity(nomination["text"]),
                )
            )
        sources = [(region["body_context"], body_context_window(scope))]
        if (
            scope.get("kind") != "continued_unruled_columns"
            and scope["context_sources"]
        ):
            packets = scope["context_sources"]
            sources.append(
                ([{"bbox": packets[0]["bbox"], "sources": packets}], packets[0]["bbox"])
            )
        for chunks, bounds in sources:
            validate_source_window(chunks, bounds)
            tokens = window_source_tokens(chunks, bounds)
            for nomination in continuation_nominees(
                tokens,
                scope["page_size"],
                native_tokens=window_source_tokens(chunks, bounds, native=True),
            ):
                identity = continuation_identity(nomination["text"])
                if identity[0] == qualified_table_key(scope):
                    observed[
                        (scope["page_no"], tuple(nomination["bbox"]), identity)
                    ] = nomination
    issues = []
    for (page, bounds, identity), nomination in observed.items():
        if (page, bounds, identity) in registered:
            continue
        if any(
            repeated_header_covers(r["header_scope"], r["page_diagrams"], nomination)
            for r in by_page[page]
        ):
            continue
        issues.append(
            {
                "cpd": "",
                "page_no": page,
                "reason": "unresolved_original_unruled_continuation",
                "bbox": list(bounds),
                "table_key": identity[0],
            }
        )
    return issues
