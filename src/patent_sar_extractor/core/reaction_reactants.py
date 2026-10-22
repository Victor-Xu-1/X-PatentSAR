"""Bounded explicit addition ink links inputs of the SAME observed reaction.

No new page lane, OCR, chemical identity, reaction model or nearest-ID ranking.
Native plus primitives are retained, not erased. Glyph/raster/unsupported marks
remain blocking source ink; a drawing beside a shaft alone proves no input role.
"""

import math
from collections import defaultdict, deque

from .reaction_arrows import JOIN_TOLERANCE, contained, segment_bounds
from .reaction_connections import check_source_corridor, visible_endpoint
from .reaction_operators import validate_native_operators
from .source_geometry import overlaps

MAX_ADDITION_STROKES = 2048
MAX_ADDITION_SIGNS = 512
MAX_ADDITION_WORK = 2_000_000


def _addition_ink(observation, protected):
    if observation["version"] != 2:
        return []  # Binary arrow geometry does not prove an addition symbol.
    segments, grid, eligible = observation["segments"], defaultdict(list), []
    for index, line in enumerate(segments):
        box = segment_bounds(line)
        if (
            4 <= math.dist(line[:2], line[2:]) <= 24
            and contained(box, observation["bounds"])
            and not any(overlaps(box, region) for region in protected)
        ):
            center = [(line[axis] + line[axis + 2]) / 2 for axis in range(2)]
            key = tuple(math.floor(v / JOIN_TOLERANCE) for v in center)
            grid[key].append((index, center))
            eligible.append((index, center, key))
    if len(eligible) > MAX_ADDITION_STROKES:
        raise ValueError("Original addition-stroke inventory exceeds its bound")
    signs = []
    for first, center, (x, y) in eligible:
        neighbors = [
            (other, point)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for other, point in grid.get((x + dx, y + dy), ())
            if other > first and math.dist(center, point) <= JOIN_TOLERANCE
        ]
        if len(neighbors) > 8:
            raise ValueError("Original addition has competing central strokes")
        a = [segments[first][axis + 2] - segments[first][axis] for axis in range(2)]
        for second, other in neighbors:
            b = [
                segments[second][axis + 2] - segments[second][axis] for axis in range(2)
            ]
            lengths = math.hypot(*a), math.hypot(*b)
            if not 0.75 <= lengths[0] / lengths[1] <= 4 / 3:
                continue
            if abs(sum(a[i] * b[i] for i in range(2))) > 0.02 * math.prod(lengths):
                continue
            signs.append(
                {
                    "segments": [first, second],
                    "center": [(center[i] + other[i]) / 2 for i in range(2)],
                }
            )
            if len(signs) > MAX_ADDITION_SIGNS:
                raise ValueError("Original addition-sign inventory exceeds its bound")
    return signs


def _axis_aligned(sign, segments, direction):
    # A printed X is not an addition. Both arms must agree with the reaction's
    # along/across axes, rather than merely being any two intersecting lines.
    if "glyph_index" in sign:
        return True  # Literal + is independently source/paint qualified, not an X.
    aligned = []
    for index in sign["segments"]:
        line = segments[index]
        delta = [line[i + 2] - line[i] for i in range(2)]
        along = abs(sum(delta[i] * direction[i] for i in range(2))) / math.hypot(*delta)
        aligned.append(along)
    return min(aligned) <= 0.02 and max(aligned) >= 0.999


def _links(observation, diagrams, protected, step, signs):
    length = math.dist(step["tail"], step["tip"])
    direction = [(step["tip"][i] - step["tail"][i]) / length for i in range(2)]
    links = []
    for sign in signs:
        if not _axis_aligned(sign, observation["segments"], direction):
            continue
        # Every input, symbol and corridor must precede the actual shaft tail.
        if (
            sum((sign["center"][i] - step["tail"][i]) * direction[i] for i in range(2))
            >= 0
        ):
            continue
        ends = []
        for ray in ([-v for v in direction], direction):
            identity, corridor = visible_endpoint(
                sign["center"],
                ray,
                diagrams,
                length,
                source_bounds=observation["bounds"],
            )
            check_source_corridor(
                observation,
                {**sign, "heads": []},
                diagrams,
                protected,
                corridor,
            )
            diagram = next(d for d in diagrams if d["structure_id"] == identity)
            box = diagram["bbox"]
            if (
                max(
                    (x - step["tail"][0]) * direction[0]
                    + (y - step["tail"][1]) * direction[1]
                    for x in (box[0], box[2])
                    for y in (box[1], box[3])
                )
                >= 0
            ):
                raise ValueError("Addition input crosses the original reaction shaft")
            ends.append(identity)
        if ends[0] == ends[1]:
            raise ValueError("Addition cannot join a drawing to itself")
        links.append({"input_ids": ends, **sign})
    return links


def explicit_reactant_groups(observation, diagrams, protected, report, *, operators):
    """Return reproducible source witnesses; the sole route graph owns acceptance."""
    validate_native_operators(operators, observation, protected)
    signs = _addition_ink(observation, protected)
    signs.extend(
        {
            "segments": [],
            "glyph_index": index,
            "owned_blockers": [cell["bbox"]],
            "center": [(cell["bbox"][i] + cell["bbox"][i + 2]) / 2 for i in range(2)],
        }
        for index, cell in enumerate(operators)
    )
    if len(signs) > MAX_ADDITION_SIGNS:
        raise ValueError("Combined original addition-sign inventory exceeds its bound")
    work = (
        len(signs)
        * len(report["steps"])
        * (
            len(observation["segments"])
            + len(observation["blockers"])
            + len(observation["filled_heads"])
            + len(diagrams)
            + len(protected)
        )
    )
    if work > MAX_ADDITION_WORK:
        raise ValueError("Original addition-source work exceeds its bound")
    groups = []
    for index, step in enumerate(report["steps"]):
        if step["input_port"] is not None or step["output_port"] is not None:
            continue  # No addition sign repairs a missing reaction endpoint.
        links = _links(observation, diagrams, protected, step, signs)
        adjacent = defaultdict(set)
        for link in links:
            first, last = link["input_ids"]
            adjacent[first].add(last)
            adjacent[last].add(first)
        ready, members = deque([step["from"]]), set()
        while ready:
            current = ready.popleft()
            if current in members:
                continue
            members.add(current)
            ready.extend(adjacent[current] - members)
        if len(members) > 1:
            groups.append(
                {
                    "step_index": index,
                    "input_ids": [
                        d["structure_id"]
                        for d in diagrams
                        if d["structure_id"] in members
                    ],
                    "connectors": [
                        link for link in links if set(link["input_ids"]) <= members
                    ],
                }
            )
    return groups
