"""Local physical-column identity and complete registered-source projection."""

import re

from .activity_context_geometry import validate_grid_axes
from .source_observations import source_observation_status
from .source_window_chunks import source_packet_projection
from .structure_table_headers import aligned_column_edges
from .unruled_scope import scope_axes, scope_roles


def valid_ruled_header_binding(binding):
    try:
        evidence = binding["numbered_table_cell_evidence"]
        ownership = evidence["column_ownership"]
        scope = ownership["header_scope"]
        roles = scope_roles(scope)
        row, pair, axes = evidence["row"], evidence["pair"], ownership["grid_axes"]
        validate_grid_axes(
            axes, [axes["xs"][0], axes["ys"][0], axes["xs"][-1], axes["ys"][-1]]
        )
        first_row = int(scope.get("kind") == "original_ruled_columns")
        if (
            roles is None
            or roles["role"] != "compound"
            or evidence["kind"] != "original_ruled_columns"
            or binding.get("source_pdf_sha256") != scope["original_pdf_sha256"]
            or binding.get("page_no") != scope["page_no"]
            or evidence["page_no"] != scope["page_no"]
            or not isinstance(ownership["source_anchor_id"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", ownership["source_anchor_id"])
            or scope.get("kind")
            not in {"original_ruled_columns", "continued_unruled_columns"}
            or ownership["headers"] != roles["headers"]
            or ownership["grid_xs"] != axes["xs"]
            or first_row
            and axes != scope["grid_axes"]
            or not first_row
            and (
                not aligned_column_edges(scope_axes(scope)[0], axes["xs"])
                or axes["ys"][0] < scope_axes(scope)[1][1]
            )
            or type(row) is not int
            or not first_row <= row < len(axes["ys"]) - 1
            or type(pair) is not int
            or not 0 <= pair < len(roles["pairs"])
            or (ownership["identifier_column"], ownership["structure_column"])
            != roles["pairs"][pair]
        ):
            return False
        identifier, structure = roles["pairs"][pair]
        return evidence["label_bbox"] == [
            axes["xs"][identifier],
            axes["ys"][row],
            axes["xs"][identifier + 1],
            axes["ys"][row + 1],
        ] and evidence["structure_cell_bbox"] == [
            axes["xs"][structure],
            axes["ys"][row],
            axes["xs"][structure + 1],
            axes["ys"][row + 1],
        ]
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False


def validate_ruled_source_reference(parent, binding):
    if not valid_ruled_header_binding(binding):
        raise ValueError("Unproved original ruled column/header ownership")
    evidence, source = binding["numbered_table_cell_evidence"], parent["source"]
    if {"id": binding["structure_id"], "bbox": evidence["segment_bbox"]} not in source[
        "page_diagrams"
    ] or evidence["label_bbox"][3] > source["body_bottom"]:
        raise ValueError(
            "Ruled binding differs from complete original diagram/body scope"
        )
    observed = [
        o["source_observation"]
        for o in evidence["observations"]
        if "source_observation" in o
    ]
    if not observed:
        raise ValueError("Original ruled label has no retained source observation")
    for packet in observed:
        box = evidence["label_bbox"]
        if source_observation_status(
            packet, box, packet.get("text")
        ) == "invalid" or not source_packet_projection(
            packet, source["body_context"], box
        ):
            raise ValueError(
                "Original ruled label projection differs from complete source"
            )
