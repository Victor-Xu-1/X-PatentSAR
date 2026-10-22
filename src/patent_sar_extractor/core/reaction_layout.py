"""Unique contiguous wrapped-source interpretations of explicit original ports.

An endpoint resolution is not an observed stroke or an additional reaction. It
binds a still-retained local arrow port to one unique neighboring source root or
terminal under the caller's complete single-heading declaration. Closed routes
cannot be joined just because they occur one after another. No gap/page is skipped.
"""

import math
from itertools import pairwise

from .reaction_arrows import MAX_ARROW_COUNT, segment_bounds
from .reaction_heads import head_bounds
from .reaction_layout_components import component_reference, local_components
from .source_geometry import overlaps

MAX_LAYOUT_GAP_WORK = 2_000_000


def _horizontal(port, bounds):
    x, y = port["source_boundary"]
    edge = bounds[2] if port["direction"][0] > 0 else bounds[0]
    margin = port["boundary_margin"]
    return (
        abs(port["direction"][0]) >= 0.999
        and abs(port["direction"][1]) <= 0.02
        and math.isclose(x, edge, abs_tol=1e-6, rel_tol=0)
        and bounds[1] + margin < y < bounds[3] - margin
    )


def _clear_source_gap(before, after, pages, diagrams, protected):
    first, last = before["page_no"], after["page_no"]
    if first == last:
        windows = [
            (
                first,
                [
                    pages[first]["bounds"][0],
                    before["bbox"][3],
                    pages[first]["bounds"][2],
                    after["bbox"][1],
                ],
            )
        ]
    else:
        windows = [
            (
                first,
                [
                    pages[first]["bounds"][0],
                    before["bbox"][3],
                    pages[first]["bounds"][2],
                    pages[first]["bounds"][3],
                ],
            ),
            (
                last,
                [
                    pages[last]["bounds"][0],
                    pages[last]["bounds"][1],
                    pages[last]["bounds"][2],
                    after["bbox"][1],
                ],
            ),
        ]
    for number, window in windows:
        owned = {tuple(drawing["bbox"]) for drawing in diagrams[number]}
        if any(
            overlaps(window, box) and tuple(box) not in owned
            for box in protected[number]
        ):
            raise ValueError("Wrapped source crosses an independently owned region")
        source = pages[number]
        if (
            any(overlaps(window, box) for box in source["blockers"])
            or any(
                overlaps(window, segment_bounds(line)) for line in source["segments"]
            )
            or any(
                overlaps(window, head_bounds(head)) for head in source["filled_heads"]
            )
        ):
            raise ValueError("Wrapped source crosses unowned original source ink")


def _join(before, after, reports):
    outputs, inputs = before["outputs"], after["inputs"]
    if not outputs and not inputs:
        return None
    if outputs and inputs or len(outputs) > 1 or len(inputs) > 1:
        raise ValueError("Wrapped source has competing or mutually missing endpoints")
    if len(before["terminals"]) != 1:
        raise ValueError("Wrapped predecessor lacks a unique complete terminal")
    if outputs:
        if len(after["roots"]) != 1:
            raise ValueError("Wrapped successor lacks a unique complete entry")
        number, index, endpoint = before["page_no"], outputs[0], "to"
        step = reports[number]["steps"][index]
        port = step["output_port"]
        if step["from"] != before["terminals"][0]:
            raise ValueError("Wrapped output does not leave its source terminal")
        identity = after["roots"][0]
    else:
        if not before["step_indices"]:
            raise ValueError(
                "Unowned standalone drawing cannot supply an earlier route"
            )
        number, index, endpoint = after["page_no"], inputs[0], "from"
        step = reports[number]["steps"][index]
        port = step["input_port"]
        if step["to"] not in after["roots"]:
            raise ValueError("Wrapped input does not enter an original source root")
        identity = before["terminals"][0]
    if not _horizontal(port, reports[number]["bounds"]):
        raise ValueError("Wrapped source has no proved horizontal row port")
    return {
        "kind": "wrapped_row"
        if before["page_no"] == after["page_no"]
        else "wrapped_page",
        "before": component_reference(before),
        "after": component_reference(after),
        "port": {
            "page_no": number,
            "step_index": index,
            "endpoint": endpoint,
            "original": port,
        },
        "resolved_structure_id": identity,
    }


def resolve_layout_endpoints(pages, candidates, reports, groups, protected):
    if not any(
        step["input_port"] is not None or step["output_port"] is not None
        for report in reports.values()
        for step in report["steps"]
    ):
        return {}, []
    if sum(len(report["steps"]) for report in reports.values()) > MAX_ARROW_COUNT:
        raise ValueError("Wrapped route exceeds its complete step budget")
    numbers = [page["page_no"] for page in pages]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise ValueError("Wrapped route cannot skip or reorder original pages")
    page_map = {page["page_no"]: page for page in pages}
    diagrams = {
        number: [d for d in candidates if d["page_no"] == number] for number in numbers
    }
    ordered = []
    for number in numbers:
        parts = local_components(
            page_map[number], diagrams[number], reports[number], groups[number]
        )
        if not parts:
            raise ValueError("Wrapped route cannot skip an empty original page")
        if any(first["bbox"][3] >= last["bbox"][1] for first, last in pairwise(parts)):
            raise ValueError("Wrapped rows overlap or have competing source entries")
        ordered.extend(parts)
    resolutions, joins, gap_work = {}, [], 0
    for before, after in pairwise(ordered):
        join = _join(before, after, reports)
        if join is None:
            continue
        for number in {before["page_no"], after["page_no"]}:
            gap_work += sum(
                len(page_map[number][kind])
                for kind in ("segments", "blockers", "filled_heads")
            ) + len(protected[number])
        if gap_work > MAX_LAYOUT_GAP_WORK:
            raise ValueError("Wrapped route exceeds its complete source-gap work bound")
        _clear_source_gap(before, after, page_map, diagrams, protected)
        port = join["port"]
        key = port["page_no"], port["step_index"], port["endpoint"]
        if key in resolutions:
            raise ValueError(
                "One original port cannot have two wrapped interpretations"
            )
        resolutions[key] = join["resolved_structure_id"]
        joins.append(join)
    return resolutions, joins
