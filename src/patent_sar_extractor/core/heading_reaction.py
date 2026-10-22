"""Compose and replay source-bound native reaction direction under one heading."""

from .heading_column_sources import independent_columns
from .heading_declaration_scope import declaration_candidates
from .heading_original_replay import validate_original_heading
from .heading_panel_scope import panel_bounds
from .reaction_graph import terminal_reaction_source
from .reaction_vectors import observe_vectors, validate_vectors
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
        or observation["version"] != 2
        or observation["status"] != "observed_native_reaction"
        or observation["original_pdf_sha256"] != heading["original_pdf_sha256"]
        or observation["declaration_scope_id"] != proof_id(scope)
        or not isinstance(observation["pages"], list)
        or len(observation["pages"]) != len(scope["pages"])
        or observation["identity"]
        != proof_id({k: v for k, v in observation.items() if k != "identity"})
    ):
        raise ValueError("Native reaction source identity differs")
    for actual, original in zip(observation["pages"], scope["pages"], strict=True):
        validate_vectors(actual)
        if (
            actual["page_no"] != original["page_no"]
            or actual["page_size"] != original["page_size"]
            or actual["bounds"] != _bounds(scope, heading, original)
        ):
            raise ValueError("Native reaction source window was shortened or changed")
    terminal = terminal_reaction_source(
        candidates, observation["pages"], source_regions=_source_regions(scope, heading)
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
    pages = [
        observe_vectors(
            document[p["page_no"] - 1],
            _bounds(scope, heading, p),
            original_frame=panel_bounds(scope["panel"], heading)
            if scope.get("version") == 4
            else None,
        )
        for p in scope["pages"]
    ]
    observation = {
        "version": 2,
        "status": "observed_native_reaction",
        "original_pdf_sha256": heading["original_pdf_sha256"],
        "declaration_scope_id": proof_id(scope),
        "pages": pages,
        "terminal_structure_id": terminal_reaction_source(
            candidates, pages, source_regions=_source_regions(scope, heading)
        ),
    }
    observation["identity"] = proof_id(observation)
    reaction_source_status(observation, scope, heading)
    return observation
