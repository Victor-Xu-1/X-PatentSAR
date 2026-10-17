"""Original visible row fragments, subordinate to a proved characterization grid."""

import math

from .activity_grid_role_observation import observe_role_cells
from .activity_grid_roles import declared_measurement
from .cell_frame_proof import valid_cell_frame
from .cell_text_proof import valid_text_reading
from .source_fragment_context import validate_fragment_context
from .source_grid_edges import edge_intervals
from .source_section_roles import section_heading


def _normalized(text):
    return " ".join(text.split()).casefold()


def _known_role_conflict(cells):
    texts = [*cells["native_hints"][0]]
    for observed in cells["observations"]:
        texts.extend(observed["matrix"][0])
        for cell in observed["cells"]:
            texts.extend(
                part.get("text", "")
                for part in cell.get("detection_parts", [])
                if isinstance(part, dict)
            )
    return any(
        declared_measurement(text)
        or (heading := section_heading(text))
        and heading["role"] == "assay_section"
        for text in texts
    )


def observe_fragments(page, grid_edges, tokens):
    fragments = []
    xs = grid_edges["xs"]
    for interval in edge_intervals(grid_edges):
        bounds = interval["bbox"]
        cells = (
            observe_role_cells(
                page,
                {"xs": xs, "ys": [bounds[1], bounds[3]]},
                tokens,
                retain_frames=True,
            )
            if interval["status"] == "observed_columns"
            else None
        )
        fragments.append({**interval, "source_cells": cells})
    return fragments


def validate_fragments(region):
    """Replay every nominated open window; omission cannot clear an open row."""
    edges, fragments = region.get("grid_edges"), region.get("row_fragments")
    intervals = edge_intervals(edges)
    scope = region["role_scope"]
    if edges["xs"] != scope["xs"] or edges["ys"] != scope["ys"]:
        raise ValueError("Original open-row axes differ from their role source")
    if not isinstance(fragments, list) or len(fragments) != len(intervals):
        raise ValueError("Original open-row inventory was omitted or changed")
    for fragment, interval in zip(fragments, intervals):
        if not isinstance(fragment, dict) or (
            set(fragment) != {"edge", "bbox", "status", "source_cells"}
            or any(fragment.get(k) != v for k, v in interval.items())
        ):
            raise ValueError("Malformed original open-row fragment")
        cells = fragment["source_cells"]
        if interval["status"] == "unproved_columns":
            if cells is not None:
                raise ValueError("Unproved open columns have asserted cell ownership")
            continue
        if cells is None:  # Bounded renderer refused; preserve an unresolved window.
            continue
        xs, bounds = edges["xs"], interval["bbox"]
        if not isinstance(cells, dict) or (
            set(cells)
            != {"xs", "ys", "native_hints", "observations", "rendered_frames"}
            or cells["xs"] != xs
            or cells["ys"] != [bounds[1], bounds[3]]
            or not isinstance(cells["native_hints"], list)
            or len(cells["native_hints"]) != 1
            or not isinstance(cells["native_hints"][0], list)
            or len(cells["native_hints"][0]) != len(xs) - 1
            or any(
                not isinstance(t, str) or len(t) > 4096
                for t in cells["native_hints"][0]
            )
        ):
            raise ValueError("Malformed original open-row cell scope")
        observations, frames = cells["observations"], cells["rendered_frames"]
        if (
            not isinstance(observations, list)
            or not 1 <= len(observations) <= 2
            or not isinstance(frames, list)
            or len(frames) > 2
        ):
            raise ValueError("Malformed original open-row observations")
        methods = [
            o.get("method") if isinstance(o, dict) else None for o in observations
        ]
        native = methods == ["native_cells"]
        if not (native or methods == ["cell_ocr_400dpi", "cell_ocr_600dpi"]):
            raise ValueError("Unproved original open-row observation methods")
        if len(frames) != (0 if native else 2):
            raise ValueError("Missing original open-row raster frames")
        for index, observed in enumerate(observations):
            if (
                set(observed) != {"method", "matrix", "cells"}
                or not isinstance(observed["matrix"], list)
                or len(observed["matrix"]) != 1
                or not isinstance(observed["matrix"][0], list)
                or len(observed["matrix"][0]) != len(xs) - 1
                or not isinstance(observed["cells"], list)
                or len(observed["cells"]) != len(xs) - 1
                or not native
                and (
                    not isinstance(frames[index], list)
                    or len(frames[index]) != len(xs) - 1
                )
            ):
                raise ValueError("Incomplete original open-row physical columns")
            for column, reading in enumerate(observed["cells"]):
                box = [xs[column], bounds[1], xs[column + 1], bounds[3]]
                if not isinstance(reading, dict) or (
                    reading.get("bbox") != box
                    or not isinstance(reading.get("text"), str)
                    or len(reading["text"]) > 4096
                    or reading["text"] != observed["matrix"][0][column]
                ):
                    raise ValueError(
                        "Original open-row cell differs from its physical owner"
                    )
                if native:
                    if set(reading) != {"method", "text", "bbox"} or (
                        reading["method"] != "native_cell"
                        or reading["text"] != cells["native_hints"][0][column]
                    ):
                        raise ValueError("Malformed native open-row cell")
                else:
                    dpi = (400, 600)[index]
                    if (
                        set(reading) - {"physical_header_lines"}
                        != {
                            "method",
                            "text",
                            "raw_text",
                            "confidence",
                            "parts",
                            "bbox",
                            "coordinate_space",
                            "ink_crop_pixels",
                            "border_pixels",
                            "render_dpi",
                            "detection_parts",
                        }
                        or reading["method"] != f"cell_ocr_{dpi}dpi"
                        or type(reading["render_dpi"]) is not int
                        or reading["render_dpi"] != dpi
                        or reading["coordinate_space"] != "original_pdf_points"
                        or not isinstance(reading["raw_text"], str)
                        or len(reading["raw_text"]) > 4096
                        or type(reading["confidence"]) not in {int, float}
                        or not math.isfinite(reading["confidence"])
                        or not 0 <= reading["confidence"] <= 1
                        or not valid_cell_frame(
                            frames[index][column], reading, box, dpi
                        )
                    ):
                        raise ValueError(
                            "Invalid original open-row pixel frame or text scope"
                        )
                    if any(
                        not isinstance(part.get("text"), str)
                        or len(part["text"]) > 4096
                        or type(part.get("confidence")) not in {int, float}
                        or not math.isfinite(part["confidence"])
                        or not 0 <= part["confidence"] <= 1
                        or type(part.get("confidence_valid", True)) is not bool
                        for part in [*reading["parts"], *reading["detection_parts"]]
                    ):
                        raise ValueError("Invalid original open-row part text or score")
    validate_fragment_context(region)


def fragment_texts(region, fragment, column):
    """Return independently qualified literal cell strings, never missing-value fill."""
    if type(column) is not int or not 0 <= column < len(
        region["role_scope"]["roles"]["columns"]
    ):
        raise ValueError("Invalid original fragment column")
    cells = fragment.get("source_cells")
    if (
        cells is None
        or fragment["status"] != "observed_columns"
        or _known_role_conflict(cells)
    ):
        return None
    xs, ys = cells["xs"], cells["ys"]
    bounds = [xs[column], ys[0], xs[column + 1], ys[1]]
    readings = [observation["cells"][column] for observation in cells["observations"]]
    if readings[0]["method"] == "native_cell":
        return [readings[0]["text"]]
    texts = []
    for reading, dpi in zip(readings, (400, 600)):
        empty = (
            reading.get("method") == f"cell_ocr_{dpi}dpi"
            and type(reading.get("render_dpi")) is int
            and reading["render_dpi"] == dpi
            and reading.get("coordinate_space") == "original_pdf_points"
            and reading.get("raw_text") == reading.get("text") == ""
            and reading.get("parts") == reading.get("detection_parts") == []
            and reading.get("ink_crop_pixels") is None
            and type(reading.get("border_pixels")) is int
            and reading["border_pixels"] == 0
            and type(reading.get("confidence")) in {int, float}
            and reading["confidence"] == 0
        )
        if not empty and not valid_text_reading(reading, bounds, dpi):
            return None
        texts.append(reading["raw_text"])
    hint = cells["native_hints"][0][column]
    if len({_normalized(text) for text in texts}) != 1 or (
        hint.strip() and _normalized(hint) != _normalized(texts[0])
    ):
        return None
    return texts


def fragment_issues(regions, resolved):
    return [
        {
            "cpd": "",
            "page_no": region["page_no"],
            "source_region": region["region_id"],
            "fragment_index": index,
            "reason": "unresolved_original_open_row",
        }
        for region in regions
        for index, _ in enumerate(region.get("row_fragments", []))
        if (region["region_id"], index) not in resolved
    ]
