"""Qualified original title semantics, independent of grid/image operations."""

import re

from .caption_role_semantics import catalog_title_role
from .source_observations import source_observation_status
from .source_table_markers import caption_table_marker, table_marker_identity


def title_key(text):
    marker = caption_table_marker(text)
    return (
        re.sub(r"\s+", "", table_marker_identity(marker.group())).upper()
        if marker
        else ""
    )


def observed_role(packets):
    qualified = [
        source_observation_status(packet, packet.get("bbox"), packet.get("text"))
        == "qualified"
        for packet in packets
    ]
    roles = {catalog_title_role(packet["text"]) for packet in packets}
    keys = {title_key(packet["text"]) for packet in packets}
    agreed = bool(packets) and all(qualified) and len(roles) == len(keys) == 1
    if agreed and ("" not in keys or roles & {"compound", "nonfinal"}):
        return next(iter(roles)), next(iter(keys))
    known = [packet for packet, valid in zip(packets, qualified) if valid]
    known_roles = {catalog_title_role(packet["text"]) for packet in known}
    known_keys = {title_key(packet["text"]) for packet in known}
    if (
        len(known_roles) > 1
        or len(known_keys) > 1
        or known_roles & {"mixed", "nonfinal", "conflict"}
    ):
        return "conflict", ""
    return "unknown", ""
