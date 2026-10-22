"""Explicit current and original-anchor sources for later-column readback."""


def _role_cells(number, scope):
    for row_index, row in enumerate(scope["observations"]):
        for column, reading in enumerate(row["cells"]):
            if row["method"] != "native_cells":
                reading = {
                    **reading,
                    "source_frame": scope["rendered_frames"][row_index][column],
                }
            yield number, "cell", reading


def column_header_sources(header):
    """Validated owners only; one nonrecursive original anchor per continuation.

    Each parent keeps its own page. No earlier caption is projected onto the
    current page and no OCR, stored path or arbitrary nested JSON is followed.
    The caller first applies the existing column-role/ancestry validators.
    """
    number, kind = header["page_no"], header.get("kind")
    yield number, "page", header["page_size"]
    if kind in {"continued_ruled_columns", "continued_unruled_columns"}:
        anchor = header["anchor_scope"]
        if not isinstance(anchor, dict) or anchor.get("kind") not in {
            None,
            "original_ruled_columns",
        }:
            raise ValueError("Later-column continuation has no original header")
        yield from column_header_sources(anchor)
        if kind == "continued_ruled_columns":
            yield number, "grid", header["grid_axes"]
        for chunk in header["leading_context"]:
            for packet in chunk["sources"]:
                yield number, "packet", packet
        if kind == "continued_unruled_columns":
            caption = header["caption"]
            for packet in caption["sources"]:
                yield number, "packet", packet
            yield from _role_cells(number, caption["role_cells"])
        return
    if kind not in {None, "original_ruled_columns"}:
        raise ValueError("Unknown original later-column header kind")
    if kind == "original_ruled_columns":
        yield number, "grid", header["grid_axes"]
    for packet in [*header["source_observations"], *header["context_sources"]]:
        yield number, "packet", packet
    yield from _role_cells(number, header["role_cells"])
