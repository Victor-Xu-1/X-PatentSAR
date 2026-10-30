"""Literal member selection from a complete original parallel title family."""

from .activity_caption_windows import shared_caption_allowed
from .caption_role_semantics import catalog_title_role, catalogue_title_boundary
from .native_title_claims import title_literal
from .source_table_markers import TABLE_MARKER, title_row_indices
from .title_context_grids import validate_parallel_title_grids


def parallel_title_text(observed, context, *, key_of):
    """Every row needs complete evidence; a known local conflict stays refused."""
    peers = validate_parallel_title_grids(context)
    if peers is None:
        return None
    chosen, independent = [], True
    for owner in range(len(peers)):
        rows = [r for r in observed if r["owner"] in (None, owner)]
        selected = title_row_indices(rows, boundary=catalogue_title_boundary)
        text = " ".join(rows[index]["text"] for index in selected)
        if (
            not selected
            or any(rows[index]["owner"] is None for index in selected)
            or not key_of(text)
        ):
            independent = False
        chosen.append(text)
    if independent:
        claims = {}
        for text in chosen:
            key, literal = key_of(text), title_literal(text)
            if key in claims and claims[key] != literal:
                return None
            claims[key] = literal
        owner = peers.index(context["grid_axes"])
        if any(
            r.get("native_conflict") and r["owner"] in {None, owner} for r in observed
        ):
            return None
        return (chosen[owner],)

    # Preserve the existing unique shared-caption authority, only when the
    # complete selected source is itself a single global original title.
    selected = title_row_indices(observed, boundary=catalogue_title_boundary)
    rows = [observed[index] for index in selected]
    text = " ".join(row["text"] for row in rows)
    if (
        not rows
        or any(row.get("native_conflict") for row in observed)
        or any(row["owner"] is not None for row in rows)
        and len({row["owner"] for row in observed}) != 1
        or len(list(TABLE_MARKER.finditer(text))) != 1
        or not key_of(text)
        or catalog_title_role(text) not in {"compound", "nonfinal"}
    ):
        return None
    tokens = [
        {
            "text": row["text"],
            "bbox": row["ink_bbox"],
            "x": (row["ink_bbox"][0] + row["ink_bbox"][2]) / 2,
            "y": (row["ink_bbox"][1] + row["ink_bbox"][3]) / 2,
        }
        for row in rows
    ]
    axes = context["grid_axes"]
    region = {**axes, "context_geometry": context["geometry"]}
    return (text,) if shared_caption_allowed((tokens,), region) else None
