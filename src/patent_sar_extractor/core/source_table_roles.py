"""Qualified original title semantics, independent of grid/image operations."""

import re

from .caption_role_semantics import catalog_title_role, catalogue_title_boundary
from .source_observations import project_source_observation
from .source_table_markers import (
    caption_table_marker,
    table_marker_identity,
    title_row_indices,
)
from .title_context_source import TITLE_CONTEXT, valid_title_context
from .title_ink_geometry import title_ink_rows
from .title_source_proof import (
    MAX_TITLE_SOURCES,
    TITLE_SOURCES,
    qualified_title_claim_agrees,
    source_title_geometry,
    source_title_text,
    title_packet_text,
)


def title_key(text):
    marker = caption_table_marker(text)
    return (
        re.sub(r"\s+", "", table_marker_identity(marker.group())).upper()
        if marker
        else ""
    )


def _discovered_titles(contexts, context):
    if not contexts or any(not valid_title_context(parent) for parent in contexts):
        return None
    source = contexts[0][TITLE_CONTEXT]["ink_source"]
    if source is None or any(
        parent[TITLE_CONTEXT]["ink_source"] != source for parent in contexts
    ):
        return None
    if context is None or source["context"] != context:
        return None
    rows = title_ink_rows(source)
    if rows is None or rows[1] is not None:
        return None
    expected = {index for index, row in enumerate(rows[0]) if row["requires_read"]}
    readings = {}
    for parent in contexts:
        records = parent.get(TITLE_SOURCES)
        if not isinstance(records, list) or len(records) > MAX_TITLE_SOURCES:
            return None
        for record in records:
            if source_title_geometry(record) is None:
                return None
            ink = record["ink_source"]
            if (
                ink is None
                or ink["inventory"] != source
                or ink["row_index"] in readings
            ):
                return None
            text = source_title_text(record)
            if (
                text is None
                or parent["origin"] != "native"
                or record["nomination_source"]
                != project_source_observation(source["native_source"], record["bbox"])
            ):
                return None
            readings[ink["row_index"]] = text
    if set(readings) != expected:
        return None
    observed = [
        {
            **row,
            "text": readings[index]
            if row["requires_read"]
            else project_source_observation(source["native_source"], row["bbox"])[
                "text"
            ],
        }
        for index, row in enumerate(rows[0])
    ]
    if "parallel_grids" in source["context"]:
        if not observed:
            # Complete native paint plus original closed rules can establish
            # no current title. That is UNKNOWN, not a terminal-product vote;
            # any continuation still needs the normal independent carry proof.
            # The 400dpi raster locator alone is never a blankness certificate.
            return (
                None
                if any(
                    p["kind"] == "fill-image" for p in source["native_window"]["paints"]
                )
                else ()
            )
        from .title_parallel_members import parallel_title_text

        return parallel_title_text(observed, source["context"], key_of=title_key)
    selected = title_row_indices(observed, boundary=catalogue_title_boundary)
    return (
        (" ".join(observed[index]["text"] for index in selected),) if selected else ()
    )


def _title_texts(packets, contexts, context):
    if context is not None and (
        "parallel_grids" in context or context.get("logical_window") is not None
    ):
        if not isinstance(packets, (list, tuple)) or len(packets) > MAX_TITLE_SOURCES:
            return None
        texts = _discovered_titles(contexts, context)
        if texts == () and packets:
            return None  # An observed nonempty claim cannot disappear as blank.
        return (
            texts
            if texts is not None
            and all(
                qualified_title_claim_agrees(packet, text)
                for packet in packets
                for text in texts
            )
            else None
        )
    if packets:
        texts = tuple(title_packet_text(packet) for packet in packets)
        return texts if all(text is not None for text in texts) else None
    return _discovered_titles(contexts, context) if contexts is not None else ()


def observed_role(packets, *, contexts=None, context=None):
    texts = _title_texts(packets, contexts, context)
    if texts is None:
        return "unresolved", ""
    roles = {catalog_title_role(text) for text in texts}
    keys = {title_key(text) for text in texts}
    agreed = bool(texts) and len(roles) == len(keys) == 1
    if agreed and ("" not in keys or roles & {"compound", "nonfinal"}):
        return next(iter(roles)), next(iter(keys))
    known_roles, known_keys = roles, keys
    if (
        len(known_roles) > 1
        or len(known_keys) > 1
        or known_roles & {"mixed", "nonfinal", "conflict"}
    ):
        return "conflict", ""
    return "unknown", ""


def title_texts(packets, *, contexts=None, context=None):
    return _title_texts(packets, contexts, context) or ()
