"""Original token-scope replay for the existing header and context authority."""

from .activity_grid_context import _prefix, prefix_parts
from .activity_header_identity import (
    compact_header,
    context_conflict,
    detector_header_conflict,
    header_conflict,
)
from .activity_headers import context_from_text, context_source_text
from .activity_identity import is_id_header
from .source_geometry import SourceTokens, native_region
from .source_observations import (
    source_cell_observation,
    source_claim_runs,
    source_observation_status,
)


def capture_header_sources(page, region, limit, tokens):
    if not isinstance(tokens, SourceTokens):
        return None
    xs, ys = region["xs"], region["ys"]
    columns = []
    for index in range(len(xs) - 1):
        bounds = (xs[index], ys[0], xs[index + 1], ys[limit])
        columns.append(
            source_cell_observation(
                tokens, bounds, native=native_region(tokens, bounds, False)
            )
        )
    bounds = (0, max(0, ys[0] - 310), page.rect.width, ys[0])
    return {
        "schema_version": 1,
        "columns": columns,
        "prefix": source_cell_observation(
            tokens, bounds, native=native_region(tokens, bounds, False)
        ),
        "native_prefix": source_cell_observation(tokens, bounds, native=True),
    }


def _column_conflict(packet, fresh):
    status = source_observation_status(
        packet, packet.get("bbox", ()), packet.get("text")
    )
    if status == "invalid":
        return True
    if is_id_header(packet["text"]) and is_id_header(fresh):
        return False
    runs = source_claim_runs(packet)
    return runs is None or any(
        detector_header_conflict(
            [{"text": text, "confidence": 1.0} for text in run], fresh
        )
        for run in runs
    )


def _context_parts(packet, region):
    if source_claim_runs(packet) is None:
        return None
    parts = prefix_parts(packet["tokens"], region)
    raw = "\n".join(" ".join(t["text"] for t in part) for part in parts)
    source = context_source_text(raw)
    start, offset, first_offset, scoped = len(raw) - len(source), 0, None, []
    for part in parts:
        if offset >= start:
            if first_offset is None:
                first_offset = offset
            scoped.append(part)
        offset += len(" ".join(t["text"] for t in part)) + 1
    if start and (
        not scoped
        or first_offset != start
        or source_claim_runs(packet, tokens=scoped[0])
        != (tuple(t["text"] for t in scoped[0]),)
    ):
        return None  # An unqualified caption cannot waive earlier known context.
    return scoped


def _context_conflict(packet, fresh, region):
    parts = _context_parts(packet, region)
    if parts is None:
        return True
    if packet["status"] == "qualified":
        raw = _prefix(packet["tokens"], region)
        return context_conflict(context_from_text(raw, raw), fresh)
    # Separate runs never bridge an unqualified word into a new table/condition.
    return any(
        context_conflict(context_from_text("", " ".join(run)), fresh)
        for part in parts
        for run in source_claim_runs(packet, tokens=part)
    )


def header_source_conflicts(snapshot, band, original_headers, original_context, fresh):
    """None means invalid original scope; flags cannot invent a hint exemption."""
    if (
        not isinstance(snapshot, dict)
        or type(snapshot.get("schema_version")) is not int
        or snapshot["schema_version"] != 1
        or not isinstance(snapshot.get("columns"), list)
        or len(snapshot["columns"]) != len(fresh.raw_headers)
    ):
        return None
    columns = snapshot["columns"]
    previous = band[0]
    conflicts = []
    for index, packet in enumerate(columns):
        if not isinstance(packet, dict):
            return None
        bounds = packet.get("bbox")
        if (
            source_observation_status(packet, bounds, packet.get("text")) == "invalid"
            or bounds[0] != previous
            or bounds[1:4:2] != list(band[1:4:2])
            or not band[0] <= bounds[0] < bounds[2] <= band[2]
        ):
            return None
        previous = bounds[2]
        conflict = _column_conflict(packet, fresh.raw_headers[index])
        # A caller-supplied original that differs from captured tokens keeps the
        # strict legacy claim, never a fabricated low-confidence provenance.
        if original_headers and compact_header(
            original_headers[index]
        ) != compact_header(packet["text"]):
            conflict |= header_conflict(
                original_headers[index], fresh.raw_headers[index]
            )
        conflicts.append(conflict)
    if previous != band[2]:
        return None
    region = {"xs": [band[0]], "ys": [band[1]]}
    contexts = []
    for name in ("prefix", "native_prefix"):
        packet = snapshot.get(name)
        if not isinstance(packet, dict):
            return None
        bounds = packet.get("bbox")
        if (
            source_observation_status(packet, bounds, packet.get("text")) == "invalid"
            or bounds[0] != 0
            or bounds[2] < band[2]
            or bounds[1] != max(0, band[1] - 310)
            or bounds[3] != band[1]
            or name == "native_prefix"
            and packet.get("origin") != "native"
        ):
            return None
        contexts.append(_context_conflict(packet, fresh.context, region))
    captured = _prefix(snapshot["prefix"]["tokens"], region)
    if original_context and compact_header(original_context) != compact_header(
        captured
    ):
        contexts.append(
            context_conflict(
                context_from_text(original_context, original_context), fresh.context
            )
        )
    return conflicts, any(contexts)


def _context_choice(packet, region, fresh):
    parts = _context_parts(packet, region)
    if parts is None:
        return None
    names = ("target", "assay", "cell_line")
    if any(
        source_claim_runs(packet, tokens=part) != (tuple(t["text"] for t in part),)
        for part in parts
    ):
        missing = any(
            getattr(context_from_text("", " ".join(run)), key)
            and not getattr(fresh, key)
            for part in parts
            for run in source_claim_runs(packet, tokens=part)
            for key in names
        )
        return None if missing else fresh
    raw = "\n".join(" ".join(t["text"] for t in part) for part in parts)
    source = context_from_text(raw, raw)
    if not source.table_id or source.table_id != fresh.table_id:
        return fresh
    if not any(getattr(source, key) and not getattr(fresh, key) for key in names):
        return fresh
    if any(
        getattr(fresh, key) and getattr(fresh, key) != getattr(source, key)
        for key in names
    ):
        return None
    return source


def select_header_context(snapshot, band, fresh):
    """Keep one complete observed window; never synthesize a mixed context."""
    if snapshot is None:
        return fresh
    region = {"xs": [band[0]], "ys": [band[1]]}
    selected = fresh
    for name in ("prefix", "native_prefix"):
        if name not in snapshot:
            continue
        selected = _context_choice(snapshot[name], region, selected)
        if selected is None:
            return None
    return selected
