"""Physical continuation proof for generic activity panels, not value inference."""

from dataclasses import dataclass, replace

from .activity_grid_cells import continuation_prefix
from .activity_models import GridSchema, TableContext


@dataclass(frozen=True)
class Panel:
    page: int
    region: dict
    schema: GridSchema


def continued_panel(
    previous: list[Panel], page: int, region: dict, context: TableContext, prefix: str
) -> GridSchema | None:
    xs, ys = region["xs"], region["ys"]
    candidates = []
    for old in previous:
        ox, oy = old.region["xs"], old.region["ys"]
        if len(ox) != len(xs):
            continue
        same_columns = all(abs((a - ox[0]) - (b - xs[0])) <= 4 for a, b in zip(ox, xs))
        parallel = (
            old.page == page
            and abs(oy[0] - ys[0]) <= 4
            and ox[-1] < xs[0]
            and same_columns
            and bool(old.schema.context.table_id)
            and (
                context.table_id == old.schema.context.table_id
                or not context.table_id
                and context.raw_context
                == (old.schema.header_resolution or {}).get("original_context")
            )
        )
        adjacent = (
            old.page + 1 == page
            and ys[0] < 130
            and all(abs(a - b) <= 4 for a, b in zip(ox, xs))
            and continuation_prefix(prefix)
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
    return replace(candidates[0], first_data_row=0)
