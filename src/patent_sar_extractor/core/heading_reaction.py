"""Compose and replay source-bound original reaction direction under one heading."""

from .heading_column_sources import independent_columns
from .heading_declaration_scope import declaration_candidates
from .heading_original_replay import validate_original_heading
from .heading_panel_scope import panel_bounds
from .reaction_graph import terminal_reaction_source
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
        or type(observation["version"]) is not int
        or observation["version"] not in {2, 3}
        or observation["status"]
        != (
            "observed_native_reaction"
            if observation["version"] == 2
            else "observed_pixel_reaction"
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
    if has_pixels != (observation["version"] == 3):
        raise ValueError("Original reaction observation kind differs from its sources")
    terminal = terminal_reaction_source(
        candidates, pages, source_regions=regions, endpoint_uncertainty=errors
    )
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
    observation = {
        "version": 3 if has_pixels else 2,
        "status": "observed_pixel_reaction"
        if has_pixels
        else "observed_native_reaction",
        "original_pdf_sha256": heading["original_pdf_sha256"],
        "declaration_scope_id": proof_id(scope),
        "pages": pages,
        "terminal_structure_id": terminal_reaction_source(
            candidates,
            geometric,
            source_regions=regions,
            endpoint_uncertainty={
                page["page_no"]: value
                for page, value in zip(geometric, uncertainty, strict=True)
            },
        ),
    }
    observation["identity"] = proof_id(observation)
    reaction_source_status(observation, scope, heading)
    return observation
