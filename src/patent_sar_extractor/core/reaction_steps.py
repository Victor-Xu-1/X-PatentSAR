"""Complete local source steps and unresolved ports for the one route parser.

Ports record an original boundary, not a reaction edge, layout role or molecule.
The strict graph consumes only fully connected steps; no missing endpoint, input
annotation, row order, number or model prediction can silently supply an edge.
"""

import math

from .reaction_arrows import contained, vector_arrows
from .reaction_connections import (
    MissingReactionEndpoint,
    check_source_corridor,
    open_source_ray,
    visible_endpoint,
)
from .reaction_vectors import valid_rectangle, validate_vectors

MAX_REACTION_DIAGRAMS = 256


def _source_uncertainty(observation, diagrams, uncertainty):
    validate_vectors(observation)
    if (
        not isinstance(diagrams, list)
        or len(diagrams) > MAX_REACTION_DIAGRAMS
        or any(
            not isinstance(d, dict)
            or not isinstance(d.get("structure_id"), str)
            or not 0 < len(d["structure_id"]) <= 256
            for d in diagrams
        )
        or len({d["structure_id"] for d in diagrams}) != len(diagrams)
    ):
        raise ValueError("Reaction drawing inventory is malformed or exceeds its bound")
    if any(
        not valid_rectangle(diagram.get("bbox"), observation["page_size"])
        or not contained(diagram["bbox"], observation["bounds"])
        for diagram in diagrams
    ):
        raise ValueError("A reaction drawing leaves its complete original source")
    uncertainty = {} if uncertainty is None else uncertainty
    if not isinstance(uncertainty, dict) or any(
        type(index) is not int
        or not 0 <= index < len(observation["segments"])
        or type(error) not in {int, float}
        or not math.isfinite(error)
        or not 0 <= error <= math.hypot(*observation["page_size"])
        for index, error in uncertainty.items()
    ):
        raise ValueError("Invalid original arrow coordinate uncertainty")
    if observation["version"] == 3 and (
        set(uncertainty) != set(range(len(observation["segments"])))
        or any(error <= 0 for error in uncertainty.values())
    ):
        raise ValueError("Pixel reaction geometry lost its coordinate uncertainty")
    return uncertainty


def _endpoint(observation, arrow, diagrams, protected, point, direction, length, error):
    try:
        identity, corridor = visible_endpoint(
            point,
            direction,
            diagrams,
            length,
            error=error,
            source_bounds=observation["bounds"],
        )
        if error and not contained(corridor, observation["bounds"]):
            raise ValueError("Pixel connection uncertainty leaves its source window")
        port = None
    except MissingReactionEndpoint:
        identity = None
        port = open_source_ray(
            point,
            direction,
            diagrams,
            length,
            error=error,
            source_bounds=observation["bounds"],
        )
        corridor = port["corridor"]
    check_source_corridor(observation, arrow, diagrams, protected, corridor)
    return identity, port


def page_reaction_steps(observation, diagrams, protected_regions, uncertainty=None):
    """No original candidate/arrow is omitted to manufacture a complete route."""
    uncertainty = _source_uncertainty(observation, diagrams, uncertainty)
    arrow_regions = (
        [
            region
            for region in protected_regions
            if not any(region == d["bbox"] for d in diagrams)
        ]
        if observation["version"] == 3
        else protected_regions
    )
    arrows = vector_arrows(observation, arrow_regions, uncertainty=uncertainty)
    steps, assigned = [], set()
    for arrow in arrows:
        tail, tip = arrow["tail"], arrow["tip"]
        length = math.dist(tail, tip)
        error = max((uncertainty.get(i, 0.0) for i in arrow["segments"]), default=0.0)
        if error and length < 4 * error:
            raise ValueError("Pixel shaft is too short to establish a stable direction")
        direction = [(tip[i] - tail[i]) / length for i in range(2)]
        first, input_port = _endpoint(
            observation,
            arrow,
            diagrams,
            protected_regions,
            tail,
            [-v for v in direction],
            length,
            error,
        )
        last, output_port = _endpoint(
            observation,
            arrow,
            diagrams,
            protected_regions,
            tip,
            direction,
            length,
            error,
        )
        if first is not None and first == last:
            raise ValueError("Native arrow cannot connect a drawing to itself")
        assigned.update(identity for identity in (first, last) if identity is not None)
        steps.append(
            {
                "from": first,
                "to": last,
                "tail": list(tail),
                "tip": list(tip),
                "segments": list(arrow["segments"]),
                "heads": list(arrow["heads"]),
                "coordinate_error": error,
                "input_port": input_port,
                "output_port": output_port,
            }
        )
    return {
        "page_no": observation["page_no"],
        "bounds": list(observation["bounds"]),
        "diagram_ids": [diagram["structure_id"] for diagram in diagrams],
        "steps": steps,
        "unassigned": [
            d["structure_id"] for d in diagrams if d["structure_id"] not in assigned
        ],
    }
