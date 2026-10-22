"""One original literal-cell observer and validator for figure text and legends."""

from .activity_grid_role_observation import observe_role_cells
from .cell_frame_proof import inside_box
from .plot_reference_geometry import literal, literal_bounds
from .source_observations import project_source_observation, source_observation_status
from .source_window_chunks import observe_window_sources, source_packet_projection
from .unruled_header_readings import original_header_readings


def observe_literal_cell(page, part, size, tokens):
    box = literal_bounds(part["bbox"], size)
    return {
        "bbox": box,
        "sources": observe_window_sources(tokens, box),
        "reading": observe_role_cells(
            page,
            {"xs": [box[0], box[2]], "ys": [box[1], box[3]]},
            tokens,
            retain_frames=True,
        ),
    }


def literal_cell_text(cell, box, *, chunks=None):
    if (
        not isinstance(cell, dict)
        or set(cell) != {"bbox", "sources", "reading"}
        or cell["bbox"] != box
        or not isinstance(cell["sources"], list)
        or not 1 <= len(cell["sources"]) <= 2
        or not isinstance(cell["reading"], dict)
        or [p.get("origin") if isinstance(p, dict) else None for p in cell["sources"]]
        not in (["native"], ["raster", "native"])
    ):
        return None
    for packet in cell["sources"]:
        if (
            not isinstance(packet, dict)
            or source_observation_status(packet, box, packet.get("text")) == "invalid"
            or chunks is not None
            and not source_packet_projection(packet, chunks, box)
        ):
            return None
    values = original_header_readings(
        cell["reading"],
        [box[0], box[2]],
        [box[1], box[3]],
        cell["sources"],
        identity=literal,
    )
    if values is None or not values[0].strip():
        return None
    if chunks is not None:
        parents = [chunk for chunk in chunks if inside_box(box, chunk["bbox"])]
        if len(parents) != 1:
            return None
        # A projected carrier cannot remove native/raster contradictions from
        # the complete parent. Agreement of two cropped reads is insufficient.
        for original in parents[0]["sources"]:
            retained = project_source_observation(original, box)
            if (
                retained["status"] == "qualified"
                and retained["text"].strip()
                and literal(retained["text"]) != literal(values[0])
            ):
                return None
    return values[0]


def literal_cells_match(parts, cells, size, *, chunks):
    return bool(
        isinstance(cells, list)
        and len(cells) == len(parts)
        and all(
            (
                text := literal_cell_text(
                    cell, literal_bounds(part["bbox"], size), chunks=chunks
                )
            )
            is not None
            and literal(text) == literal(part["text"])
            for part, cell in zip(parts, cells)
        )
    )
