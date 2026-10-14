"""Physical continuation proof for generic activity panels, not value inference."""

from dataclasses import dataclass, replace

from .activity_continuation_policy import (
    canonical_header,
    caption_prefix,
    continuation_allowed,
)
from .activity_models import GridSchema, TableContext


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
) -> GridSchema | None:
    xs, ys = region["xs"], region["ys"]
    candidates = []
    for old in previous:
        ox, oy = old.region["xs"], old.region["ys"]
        if len(ox) != len(xs):
            continue
        if current and (
            tuple(map(canonical_header, current.raw_headers))
            != tuple(map(canonical_header, old.schema.raw_headers))
            or any(
                (value := getattr(current.context, key)) is not None
                and (prior := getattr(old.schema.context, key)) is not None
                and value != prior
                for key in ("target", "cell_line")
            )
        ):
            continue
        same_columns = all(abs((a - ox[0]) - (b - xs[0])) <= 4 for a, b in zip(ox, xs))
        parallel = (
            old.page == page
            and abs(oy[0] - ys[0]) <= 4
            and ox[-1] < xs[0]
            and same_columns
            and bool(old.schema.context.table_id)
            and caption_prefix(
                prefix, old.schema.context.table_id, old.schema.context.raw_context
            )
        )
        adjacent = (
            old.page + 1 == page
            and ys[0] < 130
            and all(abs(a - b) <= 4 for a, b in zip(ox, xs))
            and continuation_allowed(
                prefix, old.schema.source_layout, old.schema.context
            )
        )
        if parallel or adjacent:
            candidates.append(old.schema)
    # Equally shaped competing assays must never arbitrarily win by order.
    if not candidates or any(
        (s.context, s.groups, s.header_region)
        != (candidates[0].context, candidates[0].groups, candidates[0].header_region)
        for s in candidates[1:]
    ):
        return None
    old = candidates[0]
    if current:
        return replace(
            current,
            context=old.context,
            groups=old.groups,
            header_region=old.header_region,
        )
    return replace(old, first_data_row=0)
