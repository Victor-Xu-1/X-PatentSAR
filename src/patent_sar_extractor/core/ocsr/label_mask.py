"""Source-owned caption removal, never a guess from bottom-of-image glyph shapes."""

from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from patent_sar_extractor.contracts import OCSR_PREPARATION_VERSION
from patent_sar_extractor.core.numbered_structure_pairs import _confirmed_observations
from patent_sar_extractor.core.printed_identifiers import identifier_key

from .image_preprocess import publish_png

MAX_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 8_000_000


def compound_label(item: dict) -> str:
    """One whole ID across all owners and observed labels; no substring repair."""
    owners, labels = [], []
    for key in ("cpd", "cpd_id", "compound_id", "example_id"):
        value = item.get(key)
        if value is not None and str(value).strip():
            owner = identifier_key(value, wrapped=True)
            if not owner:
                return ""
            owners.append(owner)
    if not owners:
        return ""
    for key in ("visible_label", "label"):
        value = item.get(key)
        if value is not None and str(value).strip():
            labels.append(value)
    candidates = item.get("visible_label_candidates") or []
    if not isinstance(candidates, list) or len(candidates) > 256:
        return ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return ""
        value = candidate.get("label")
        if value is not None and str(value).strip():
            labels.append(value)
    observed = [identifier_key(value, wrapped=True) for value in labels]
    return owners[0] if all(observed) and len(set(owners + observed)) == 1 else ""


def _box(value):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(n) not in (int, float) or not math.isfinite(n) for n in value)
    ):
        return None
    x0, y0, x1, y1 = value
    return (
        tuple(value)
        if 0 <= x0 < x1 <= 1_000_000
        and 0 <= y0 < y1 <= 1_000_000
        and x1 - x0 >= 0.001
        and y1 - y0 >= 0.001
        else None
    )


def _image(path):
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Caption source exceeds its byte bound")
    with Image.open(io.BytesIO(content)) as original:
        if min(original.size) < 8 or original.width * original.height > MAX_PIXELS:
            raise ValueError("Caption source exceeds its pixel bound")
        rgba = original.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        image = background.convert("RGB")
    return image, hashlib.sha256(content).hexdigest()


def source_geometry(record: dict, image_path: str) -> dict | None:
    """Describe only an exact metadata-owned segmentation crop, not a display copy."""
    if str(record.get("image_path") or "") != image_path:
        return None
    points, pixels = _box(record.get("bbox_pdf")), _box(record.get("bbox"))
    if (
        not points
        or not pixels
        or any(type(n) is not int for n in pixels)
        or type(record.get("page_no")) is not int
        or record["page_no"] < 1
        or not isinstance(record.get("structure_id"), str)
        or not record["structure_id"]
    ):
        return None
    image, digest = _image(image_path)
    if image.size != (pixels[2] - pixels[0], pixels[3] - pixels[1]):
        return None
    sx, sy = (
        image.width / (points[2] - points[0]),
        image.height / (points[3] - points[1]),
    )
    if not 0.01 <= sx <= 1000 or not math.isclose(sx, sy, rel_tol=0.001):
        return None
    return {
        "coordinate_space": "original_pdf_points",
        "bbox": list(points),
        "image_size": list(image.size),
        "image_sha256": digest,
        "page_no": record["page_no"],
        "structure_id": record["structure_id"],
    }


def _caption_box(item, label, frame, image_size, digest):
    bounds = _box(frame.get("bbox"))
    size = frame.get("image_size")
    if (
        not bounds
        or frame.get("coordinate_space") != "original_pdf_points"
        or not isinstance(size, list)
        or any(type(n) is not int for n in size)
        or size != list(image_size)
        or frame.get("image_sha256") != digest
        or type(frame.get("page_no")) is not int
        or type(item.get("page_no")) is not int
        or item["page_no"] != frame.get("page_no")
        or frame.get("structure_id")
        != (item.get("source_structure_id") or item.get("structure_id"))
    ):
        return None
    sx, sy = (
        image_size[0] / (bounds[2] - bounds[0]),
        image_size[1] / (bounds[3] - bounds[1]),
    )
    if not 0.01 <= sx <= 1000 or not math.isclose(sx, sy, rel_tol=0.001):
        return None
    caption = item.get("exact_caption_evidence")
    if (
        not isinstance(caption, dict)
        or type(caption.get("page_no")) is not int
        or caption["page_no"] != item["page_no"]
    ):
        return None
    label_box = _box(caption.get("bbox"))
    observations = caption.get("observations")
    if (
        not label_box
        or not isinstance(observations, list)
        or not 1 <= len(observations) <= 3
        or not _confirmed_observations(label, observations)
        or not (bounds[0] <= label_box[0] < label_box[2] <= bounds[2])
        or not (bounds[1] <= label_box[1] < label_box[3] <= bounds[3])
    ):
        return None
    scale = image_size[0] / (bounds[2] - bounds[0])
    x0, y0 = (
        math.floor((label_box[0] - bounds[0]) * scale) - 1,
        math.floor((label_box[1] - bounds[1]) * scale) - 1,
    )
    x1, y1 = (
        math.ceil((label_box[2] - bounds[0]) * scale) + 1,
        math.ceil((label_box[3] - bounds[1]) * scale) + 1,
    )
    if not (3 <= x0 < x1 <= image_size[0] - 3 and 3 <= y0 < y1 <= image_size[1] - 3):
        return None
    return [x0, y0, x1, y1]


def _isolated_caption(image, box):
    x0, y0, x1, y1 = box
    ink = np.asarray(image.convert("L")) < 200
    inner = ink[y0:y1, x0:x1]
    guard = ink[y0 - 3 : y1 + 3, x0 - 3 : x1 + 3].copy()
    guard[3:-3, 3:-3] = False
    # Never cut touching bonds/atoms or erase a guessed empty box.
    return bool(inner.any() and not guard.any())


def mask_visible_label(image_path: str, item: dict, output_dir: str = ""):
    """Keep the original unchanged unless original caption and crop geometry agree."""
    label, frame = compound_label(item), item.get("_ocsr_source_geometry")
    if not label or not isinstance(frame, dict) or not output_dir:
        return image_path, {}
    image, digest = _image(image_path)
    box = _caption_box(item, label, frame, image.size, digest)
    if box is None or not _isolated_caption(image, box):
        return image_path, {}
    ImageDraw.Draw(image).rectangle(
        (box[0], box[1], box[2] - 1, box[3] - 1), fill="white"
    )
    # The only changed pixels are within the proved isolated caption rectangle.
    key = hashlib.sha256(f"{digest}|{label}|{box}".encode()).hexdigest()
    target = Path(output_dir) / "ocsr_label_masked" / f"caption-{key}.png"
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    publish_png(target, encoded.getvalue())
    return str(target), {
        "ocsr_label_masked": True,
        "ocsr_label_mask_source": image_path,
        "ocsr_label_mask_label": label,
        "ocsr_label_mask_bbox": box,
        "ocsr_label_mask_proof": {
            "version": OCSR_PREPARATION_VERSION,
            "source_geometry": frame,
            "caption": item["exact_caption_evidence"],
            "source_image_sha256": digest,
        },
    }
