"""Qualified current-page observations before adjacent measurement header carry."""

from .activity_header_identity import context_conflict
from .activity_header_sources import context_source_parts, source_context_region
from .activity_headers import context_from_text
from .activity_parallel_context import validate_context_boundary
from .source_observations import source_claim_runs


def continuation_context_proved(region, prefix):
    """A matching string is not proof of a qualified current-page observation."""
    try:
        checked = validate_context_boundary(
            region, region.get("continuation_context"), prefix
        )
    except ValueError:
        return False
    if checked is None:
        return False
    scope, _, _ = checked
    snapshot = {
        "schema_version": 3,
        "context_geometry": region["context_geometry"],
        **scope,
    }
    xs, ys = region["xs"], region["ys"]
    selected = source_context_region(snapshot, [xs[0], ys[0], xs[-1], ys[1]])
    if selected is None:
        return False
    contexts = []
    names = (
        ("prefix",)
        if scope["prefix"]["origin"] == "native"
        else ("prefix", "native_prefix")
    )
    for name in names:
        packet = scope[name]
        parts = context_source_parts(packet, selected)
        if parts is None or any(
            source_claim_runs(packet, tokens=part)
            != (tuple(token["text"] for token in part),)
            for part in parts
        ):
            return False
        raw = "\n".join(" ".join(token["text"] for token in part) for part in parts)
        contexts.append(context_from_text("", raw))
    primary, native = contexts[0], contexts[-1]
    return not primary.claim_conflicts and not context_conflict(
        native, primary, partial=True
    )
