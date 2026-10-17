"""Physical continuation proof for generic activity panels, not value inference."""

from dataclasses import dataclass, replace

from .activity_continuation_policy import (
    canonical_header,
    caption_prefix,
    continuation_allowed,
)
from .activity_header_identity import schema_requires_review
from .activity_headers import grid_schema
from .activity_models import GridSchema, TableContext
from .activity_parallel_context import qualified_panel_context, shared_panel_context
from .biology_tables import biology_grid_schema


@dataclass(frozen=True)
class Panel:
    page: int
    region: dict
    schema: GridSchema


def continued_panel(
    previous: list[Panel],
    page: int,
    region: dict,
    context: TableContext,
    prefix: str,
    current: GridSchema | None = None,
    *,
    matrix: list[list[str]] | None = None,
) -> GridSchema | None:
    xs, ys = region["xs"], region["ys"]
    candidates = []
    for old in previous:
        ox, oy = old.region["xs"], old.region["ys"]
        if len(ox) != len(xs):
            continue
        if schema_requires_review(old.schema) or (
            current is not None and schema_requires_review(current)
        ):
            continue
        if current and (
            tuple(map(canonical_header, current.raw_headers))
            != tuple(map(canonical_header, old.schema.raw_headers))
        ):
            continue
        same_columns = all(abs((a - ox[0]) - (b - xs[0])) <= 4 for a, b in zip(ox, xs))
        parallel = (
            old.page == page
            and abs(oy[0] - ys[0]) <= 4
            and ox[-1] < xs[0]
            and same_columns
            and bool(old.schema.context.table_id)
            and shared_panel_context(
                old.region,
                (old.schema.source_layout or {}).get("boundary_prefix"),
                region,
                prefix,
            )
            and (
                old.schema.semantic_kind == "generic"
                or caption_prefix(
                    prefix, old.schema.context.table_id, old.schema.context.raw_context
                )
            )
        )
        adjacent = (
            old.page + 1 == page
            and ys[0] < 130
            and all(abs(a - b) <= 4 for a, b in zip(ox, xs))
            and not (
                current
                and any(
                    (value := getattr(current.context, key)) is not None
                    and (prior := getattr(old.schema.context, key)) is not None
                    and value != prior
                    for key in ("target", "cell_line")
                )
            )
            and continuation_allowed(
                prefix, old.schema.source_layout, old.schema.context
            )
        )
        if parallel and old.schema.semantic_kind == "generic":
            owned_context = qualified_panel_context(region, prefix)
            if owned_context is not None:
                candidates.append(replace(old.schema, context=owned_context))
        elif parallel or adjacent:
            candidates.append(old.schema)
    # Equally shaped competing assays must never arbitrarily win by order.
    if not candidates or any(
        (s.context, s.groups, s.header_region)
        != (candidates[0].context, candidates[0].groups, candidates[0].header_region)
        for s in candidates[1:]
    ):
        return None
    old = candidates[0]
    if current is None and matrix is not None:
        repeated = biology_grid_schema(grid_schema(old.context, matrix))
        if repeated is not None:
            # Header rows require the same source selector, not a second carry.
            return continued_panel(previous, page, region, context, prefix, repeated)
    if current:
        return replace(
            current,
            context=old.context,
            groups=old.groups,
            header_region=old.header_region,
            semantic_kind=old.semantic_kind,
            value_kinds=old.value_kinds,
        )
    return replace(old, first_data_row=0)
