"""Compose and replay source-bound original reaction direction under one heading."""

from .heading_column_sources import independent_columns
from .heading_declaration_scope import declaration_candidates
from .heading_original_replay import validate_original_heading
from .heading_panel_scope import panel_bounds
from .reaction_graph import reaction_route
from .reaction_operators import observe_native_operators
from .reaction_page_source import observe_source_page, source_page_vectors
from .source_evidence_identity import proof_id


def _bounds(scope, heading, page):
    lower = (
        heading["nomination"]["bbox"][3] if page["page_no"] == heading["page_no"] else 0
    )
    upper = (
        scope["stop"]["y"]
        if page["page_no"] == scope["stop"]["page_no"]
        else page["page_size"][1]
    )
    cell = panel_bounds(scope["panel"], heading) if scope.get("version") == 4 else None
    return [
        cell[0] if cell else 0,
        lower,
        cell[2] if cell else page["page_size"][0],
        upper,
    ]


def _source_regions(scope, heading):
    """Use the SAME proved foreign-column boundaries, never a new page split."""
    regions = {
        page["page_no"]: [s["bbox"] for s in page["structures"]]
        for page in scope["pages"]
    }
    first = scope["pages"][0]
    regions[first["page_no"]].extend(
        column["bbox"]
        for column in independent_columns(scope["column_sources"], first, heading)
        if column["active"]
    )
    return regions


def reaction_source_status(observation, scope, heading):
    """A saved terminal flag cannot replace complete source/arrow replay."""
    candidates, complete = declaration_candidates(scope, heading)
    version = observation.get("version") if isinstance(observation, dict) else None
    if (
        not complete
        or not isinstance(observation, dict)
        or set(observation)
        != {
            "version",
            "status",
            "original_pdf_sha256",
            "declaration_scope_id",
            "pages",
            "terminal_structure_id",
            "identity",
        }
        | ({"reactant_groups", "input_operators"} if version in {4, 5} else set())
        | ({"layout_joins"} if version == 5 else set())
        or type(observation["version"]) is not int
        or observation["version"] not in {2, 3, 4, 5}
        or observation["status"]
        != (
            {
                2: "observed_native_reaction",
                3: "observed_pixel_reaction",
                4: "observed_source_reaction_roles",
                5: "interpreted_source_reaction_wraps",
            }[version]
        )
        or observation["original_pdf_sha256"] != heading["original_pdf_sha256"]
        or observation["declaration_scope_id"] != proof_id(scope)
        or not isinstance(observation["pages"], list)
        or len(observation["pages"]) != len(scope["pages"])
        or observation["identity"]
        != proof_id({k: v for k, v in observation.items() if k != "identity"})
    ):
        raise ValueError("Native reaction source identity differs")
    regions = _source_regions(scope, heading)
    pages, errors = [], {}
    has_pixels = False
    for actual, original in zip(observation["pages"], scope["pages"], strict=True):
        vectors, uncertainty = source_page_vectors(
            actual,
            regions[original["page_no"]],
            original_frame=panel_bounds(scope["panel"], heading)
            if scope.get("version") == 4
            else None,
        )
        has_pixels |= "kind" in actual
        if (
            vectors["page_no"] != original["page_no"]
            or vectors["page_size"] != original["page_size"]
            or vectors["bounds"] != _bounds(scope, heading, original)
        ):
            raise ValueError("Original reaction source window was shortened or changed")
        pages.append(vectors)
        errors[original["page_no"]] = uncertainty
    if version not in {4, 5} and has_pixels != (version == 3):
        raise ValueError("Original reaction observation kind differs from its sources")
    operators = observation.get("input_operators") if version in {4, 5} else None
    if version in {4, 5} and (
        not isinstance(operators, list)
        or len(operators) != len(pages)
        or any(
            not isinstance(item, dict)
            or set(item) != {"page_no", "cells"}
            or type(item["page_no"]) is not int
            or item["page_no"] != page["page_no"]
            for item, page in zip(operators, pages, strict=True)
        )
    ):
        raise ValueError("Original reaction operator inventory is incomplete")
    route = reaction_route(
        candidates,
        pages,
        source_regions=regions,
        endpoint_uncertainty=errors,
        allow_co_reactants=version in {4, 5},
        allow_continuations=version == 5,
        input_operators={item["page_no"]: item["cells"] for item in operators}
        if operators is not None
        else None,
    )
    if version in {4, 5} and (
        version == 4
        and not route["reactant_groups"]
        or proof_id(
            {"status": "reaction_input_roles", "roles": route["reactant_groups"]}
        )
        != proof_id(
            {"status": "reaction_input_roles", "roles": observation["reactant_groups"]}
        )
    ):
        raise ValueError(
            "Original reaction input roles differ from their complete source"
        )
    if version == 5 and (
        not route["layout_joins"]
        or proof_id({"status": "reaction_layout", "joins": route["layout_joins"]})
        != proof_id({"status": "reaction_layout", "joins": observation["layout_joins"]})
    ):
        raise ValueError(
            "Wrapped reaction interpretation differs from its complete original ports"
        )
    terminal = route["terminal_structure_id"]
    if terminal != observation["terminal_structure_id"]:
        raise ValueError(
            "Native reaction terminal differs from original arrow direction"
        )
    return terminal


def observe_reaction_source(document, scope, heading):
    candidates, complete = declaration_candidates(scope, heading)
    if not complete:
        raise ValueError("Incomplete original declaration cannot prove reaction roles")
    validate_original_heading(document[heading["page_no"] - 1], heading)
    regions = _source_regions(scope, heading)
    pages = [
        observe_source_page(
            document[p["page_no"] - 1],
            _bounds(scope, heading, p),
            regions[p["page_no"]],
            original_frame=panel_bounds(scope["panel"], heading)
            if scope.get("version") == 4
            else None,
        )
        for p in scope["pages"]
    ]
    geometric, uncertainty = zip(
        *(
            source_page_vectors(
                packet,
                regions[page["page_no"]],
                original_frame=panel_bounds(scope["panel"], heading)
                if scope.get("version") == 4
                else None,
            )
            for packet, page in zip(pages, scope["pages"], strict=True)
        ),
        strict=True,
    )
    has_pixels = any("kind" in page for page in pages)
    operators = [
        {
            "page_no": page["page_no"],
            "cells": observe_native_operators(
                document[page["page_no"] - 1], page, regions[page["page_no"]]
            ),
        }
        for page in geometric
    ]
    route = reaction_route(
        candidates,
        geometric,
        source_regions=regions,
        endpoint_uncertainty={
            page["page_no"]: value
            for page, value in zip(geometric, uncertainty, strict=True)
        },
        allow_co_reactants=True,
        allow_continuations=True,
        input_operators={item["page_no"]: item["cells"] for item in operators},
    )
    has_roles = bool(route["reactant_groups"])
    has_wraps = bool(route["layout_joins"])
    observation = {
        "version": 5 if has_wraps else (4 if has_roles else (3 if has_pixels else 2)),
        "status": "interpreted_source_reaction_wraps"
        if has_wraps
        else "observed_source_reaction_roles"
        if has_roles
        else ("observed_pixel_reaction" if has_pixels else "observed_native_reaction"),
        "original_pdf_sha256": heading["original_pdf_sha256"],
        "declaration_scope_id": proof_id(scope),
        "pages": pages,
        "terminal_structure_id": route["terminal_structure_id"],
        **(
            {"reactant_groups": route["reactant_groups"], "input_operators": operators}
            if has_roles or has_wraps
            else {}
        ),
        **({"layout_joins": route["layout_joins"]} if has_wraps else {}),
    }
    observation["identity"] = proof_id(observation)
    reaction_source_status(observation, scope, heading)
    return observation
