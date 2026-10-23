"""Native header/context owners in the existing activity evidence inventory."""

from .activity_boundary_sources import layout_boundary_sources
from .source_evidence_identity import proof_id


def _context(packet, region):
    from .activity_header_sources import context_source_parts
    from .activity_headers import context_from_text

    parts = context_source_parts(packet, region)
    if parts is None:
        raise ValueError("Unproved original native context scope")
    text = "\n".join(" ".join(token["text"] for token in part) for part in parts)
    return context_from_text(text, text), [token for part in parts for token in part]


def _snapshot_sources(snapshot, band, final_context, *, primary_headers):
    from .activity_context_values import CONTEXT_IDENTITY_FIELDS
    from .activity_header_identity import compact_header
    from .activity_header_sources import source_context_region

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("columns"), list):
        raise TypeError("Missing original activity header source")
    region = source_context_region(snapshot, band)
    if region is None:
        raise ValueError("Malformed original activity context scope")
    for column in snapshot["columns"]:
        if not isinstance(column, dict):
            raise TypeError("Malformed original activity header column")
        if column.get("origin") == "native":
            yield column, column["tokens"] if primary_headers else None
    prefix, independent = snapshot["prefix"], snapshot["native_prefix"]
    source, tokens = _context(prefix, region)
    _, native_tokens = _context(independent, region)
    if prefix.get("origin") == "native":
        yield prefix, tokens
    else:
        # A mixed preferred source may contain genuine native words outside its
        # raster-owned region. They must match the independent original layer.
        selected = [token for token in tokens if token["source"] == "native"]
        if any(token not in independent["tokens"] for token in selected):
            raise ValueError("Foreign original native context token")
        if selected:
            yield independent, selected
    contributes = final_context is None or any(
        final_context.get(key)
        and compact_header(final_context[key])
        != compact_header(getattr(source, key) or "")
        for key in CONTEXT_IDENTITY_FIELDS
    )
    yield independent, native_tokens if contributes else None


def _owners(payload):
    from .activity_header_sources import header_source_conflicts
    from .activity_headers import context_from_text
    from .activity_models import GridSchema, TableContext

    for proof in payload.get("header_observations", {}).values():
        snapshot = proof.get("original_source")
        if snapshot is None:
            continue  # Historical pure format remains independently validated.
        raw = proof.get("resolved_context")
        context = context_from_text(raw, raw) if isinstance(raw, str) else None
        yield (
            proof.get("page_no"),
            _snapshot_sources(
                snapshot,
                proof["header_band_bbox"],
                vars(context) if context else None,
                primary_headers=False,
            ),
        )
    for record in (payload.get("coverage") or {}).get("regions", []):
        layout = record.get("layout")
        if layout is not None:
            for scope, _bounds in layout_boundary_sources(layout, record["page_no"]):
                xs, ys = layout["xs"], layout["ys"]
                snapshot = {
                    "schema_version": 3,
                    "context_geometry": layout["context_geometry"],
                    "columns": [],
                    **scope,
                }
                yield (
                    record["page_no"],
                    _snapshot_sources(
                        snapshot,
                        [xs[0], ys[0], xs[-1], ys[1]],
                        layout["context"],
                        primary_headers=False,
                    ),
                )
        if layout is not None and layout.get("data_start", 0) > 0:
            xs, ys, first = layout["xs"], layout["ys"], layout["data_start"]
            band = [xs[0], ys[0], xs[-1], ys[first]]
            context = TableContext(**layout["context"])
            headers = tuple(layout["raw_headers"])
            current = GridSchema(context, (), first, headers)
            checked = header_source_conflicts(
                layout.get("original_source"),
                band,
                headers,
                context.raw_context,
                current,
            )
            if checked is None or any(checked[0]) or checked[1]:
                raise ValueError(
                    "Original table headers or conditions conflict with saved claims"
                )
            yield (
                record.get("page_no"),
                _snapshot_sources(
                    layout.get("original_source"),
                    band,
                    layout["context"],
                    primary_headers=True,
                ),
            )
        transposed = record.get("transposed_layout")
        if transposed is not None:
            xs, ys = record["grid_axes"]["xs"], record["grid_axes"]["ys"]
            yield (
                record.get("page_no"),
                _snapshot_sources(
                    transposed["context_sources"],
                    [xs[0], ys[0], xs[-1], ys[transposed["header_row"] + 1]],
                    transposed["context"],
                    primary_headers=True,
                ),
            )
            yield (
                record.get("page_no"),
                (
                    (cell, cell["tokens"])
                    for column in transposed["columns"]
                    for cell in column
                    if cell.get("origin") == "native"
                ),
            )


def original_native_contexts(payload, *, maximum):
    """Bounded, deduplicated raw identity and actual native-claim visibility.

    None means an independent layer that only constrains other observations;
    an explicit token subset identifies the existing owner's positive claims.
    The latter is derived with the same caption/context authority, never a
    saved 'ignore' flag. Neither form is a new measurement parser or writer.
    """
    seen = set()
    for page, sources in _owners(payload):
        if type(page) is not int or not 1 <= page <= 20000:
            raise ValueError("Missing original native context page ownership")
        for packet, claims in sources:
            key = (
                page,
                proof_id(
                    {
                        "status": "native_activity_context",
                        "source": packet,
                        "claims": claims,
                    }
                ),
            )
            if key not in seen:
                seen.add(key)
                if len(seen) > maximum:
                    raise ValueError(
                        "Native activity contexts exceed their bounded inventory"
                    )
                yield page, packet, claims
