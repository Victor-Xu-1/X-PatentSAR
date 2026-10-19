"""Pure validation of auxiliary row observations over a retained primary cell."""

import math
import re

from patent_sar_extractor.contracts import AUXILIARY_TEXT_CELL_VERSION
from patent_sar_extractor.core.activity_header_identity import detector_header_conflict
from patent_sar_extractor.core.cell_frame_proof import inside_box, valid_cell_frame
from patent_sar_extractor.core.cell_text_limits import row_pixel_limit

from .cell_frames import MIN_AUXILIARY_SCORE, literal
from .protocol import validate_reply


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)


def primary_structure(primary, frame, bounds, dpi):
    return (
        isinstance(primary, dict)
        and "auxiliary_text" not in primary
        and primary.get("method") == f"cell_ocr_{dpi}dpi"
        and type(primary.get("render_dpi")) is int
        and primary["render_dpi"] == dpi
        and primary.get("bbox") == bounds
        and primary.get("coordinate_space") == "original_pdf_points"
        and isinstance(primary.get("raw_text"), str)
        and len(primary["raw_text"]) <= 4096
        and isinstance(primary.get("text"), str)
        and primary["text"] in ("", primary["raw_text"])
        and primary.get("source_frame", frame) == frame
        and type(primary.get("confidence")) in {int, float}
        and math.isfinite(primary["confidence"])
        and 0 <= primary["confidence"] <= 1
        and primary.get("crosses_boundary", False) is False
        and primary.get("detector_conflict", False) is False
        and valid_cell_frame(frame, primary, bounds, dpi)
        and all(
            isinstance(p.get("text"), str)
            and len(p["text"]) <= 4096
            and type(p.get("confidence")) in {int, float}
            and math.isfinite(p["confidence"])
            and 0 <= p["confidence"] <= 1
            and p.get("confidence_valid", True) is True
            for p in primary["parts"] + primary["detection_parts"]
        )
        and literal(primary["raw_text"])
        == literal(" ".join(p["text"] for p in primary["parts"]))
    )


def view_summary(view, fingerprint):
    if not isinstance(view, dict) or set(view) != {
        "dpi",
        "primary",
        "frame",
        "crop",
        "border",
        "shape",
        "pixel_sha256",
        "ink_pixels",
        "rows",
    }:
        raise ValueError("Malformed auxiliary original view")
    dpi, primary, rows = view["dpi"], view["primary"], view["rows"]
    bounds = primary.get("bbox") if isinstance(primary, dict) else None
    if (
        type(dpi) is not int
        or dpi not in (400, 600)
        or not inside_box(bounds, [0, 0, 1_000_000, 1_000_000])
        or not primary_structure(primary, view["frame"], bounds, dpi)
        or view["crop"] != primary.get("ink_crop_pixels")
        or view["border"] != primary.get("border_pixels")
        or type(view["border"]) is not int
        or view["border"] != max(3, round(dpi / 72 * 1.5))
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= 8
        or not _sha(view["pixel_sha256"])
    ):
        raise ValueError("Unproved auxiliary primary view")
    crop, border = view["crop"], view["border"]
    shape = [crop[3] - crop[1] + 2 * border, crop[2] - crop[0] + 2 * border, 3]
    if (
        view["shape"] != shape
        or type(view["ink_pixels"]) is not int
        or not 0 < view["ink_pixels"] <= shape[0] * shape[1]
    ):
        raise ValueError("Auxiliary original frame shape differs")
    parts, bottom, area = [], border - 1, 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"bbox", "observation"}:
            raise ValueError("Malformed auxiliary row")
        box, observation = row["bbox"], row["observation"]
        if (
            not inside_box(box, [border, border, shape[1] - border, shape[0] - border])
            or any(type(v) is not int for v in box)
            or box[1] <= bottom
            or box[3] - box[1] > row_pixel_limit(dpi)
            or not isinstance(observation, dict)
            or type(observation.get("cache_hit")) is not bool
        ):
            raise ValueError("Auxiliary row leaves the complete original frame")
        response = {k: v for k, v in observation.items() if k != "cache_hit"}
        request = {k: response.get(k) for k in ("id", "image_sha256", "pixel_sha256")}
        request["model_fingerprint"] = fingerprint
        if (
            not isinstance(request["id"], str)
            or not re.fullmatch(r"[a-f0-9]{32}", request["id"])
            or not all(_sha(request[k]) for k in ("image_sha256", "pixel_sha256"))
        ):
            raise ValueError("Auxiliary row identity is invalid")
        result = validate_reply(response, request)
        if not result["text"].strip() or result["confidence"] < MIN_AUXILIARY_SCORE:
            raise ValueError("Auxiliary row remains unqualified")
        x0, y0, x1, y1 = box
        parts.append(
            {
                "text": result["text"],
                "confidence": result["confidence"],
                "bbox": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                "coordinate_space": "cell_ink_crop_pixels",
                "method": "physical_header_line",
            }
        )
        bottom, area = y1, area + (x1 - x0) * (y1 - y0)
    if area < view["ink_pixels"]:
        raise ValueError("Auxiliary rows do not conserve original ink")
    text = "\n".join(p["text"] for p in parts)
    if detector_header_conflict(primary["detection_parts"], text):
        raise ValueError(
            "Auxiliary text contradicts qualified original detector claims"
        )
    old_parts = primary["parts"]
    if len(old_parts) == len(parts):
        if any(
            p["confidence"] >= 0.85 and literal(p["text"]) != literal(fresh["text"])
            for p, fresh in zip(old_parts, parts)
        ):
            raise ValueError("Auxiliary text changes a qualified original line")
    elif any(p["confidence"] >= 0.85 for p in old_parts):
        raise ValueError(
            "Qualified original rows have ambiguous auxiliary correspondence"
        )
    return {
        "detector_conflict": False,
        "text": text,
        "raw_text": text,
        "confidence": min(p["confidence"] for p in parts),
        "parts": parts,
        "ink_crop_pixels": list(crop),
        "border_pixels": border,
        "detection_parts": primary["detection_parts"],
        "source_frame": view["frame"],
        "physical_header_lines": {
            "version": AUXILIARY_TEXT_CELL_VERSION,
            "status": "observed",
            "image_shape": shape,
            "pixel_sha256": view["pixel_sha256"],
            "row_bounds": [r["bbox"] for r in rows],
            "ink_pixels": view["ink_pixels"],
        },
    }
