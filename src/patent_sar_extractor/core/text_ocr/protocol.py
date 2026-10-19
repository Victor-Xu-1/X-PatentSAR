"""One bounded literal-row protocol; neither paths nor model output are trusted."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import stat
from pathlib import Path

import numpy as np
from PIL import Image

MAX_PIXELS = 1_000_000
MAX_FILE_BYTES = 4_000_000
MAX_RSS_MB = 1024
REQUEST_FIELDS = {
    "id",
    "image_path",
    "image_sha256",
    "pixel_sha256",
    "shape",
    "model_fingerprint",
}
REPLY_FIELDS = {
    "id",
    "status",
    "image_sha256",
    "pixel_sha256",
    "model_fingerprint",
    "text",
    "confidence",
    "device",
    "peak_rss_mb",
    "confidence_kind",
}


def frame_digest(image: np.ndarray) -> str:
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or not 1 <= image.shape[0] <= 256
        or not 1 <= image.shape[1] <= 4096
        or image.shape[0] * image.shape[1] > MAX_PIXELS
    ):
        raise ValueError("Auxiliary OCR requires one bounded original RGB text row")
    digest = hashlib.sha256(json.dumps(list(image.shape)).encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def read_frame(request: dict, root: Path, fingerprint: str) -> np.ndarray:
    if (
        not isinstance(request, dict)
        or set(request) != REQUEST_FIELDS
        or not isinstance(request["id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", request["id"])
        or request["model_fingerprint"] != fingerprint
        or not isinstance(request["shape"], list)
        or len(request["shape"]) != 3
        or any(type(v) is not int for v in request["shape"])
        or any(
            not isinstance(request[k], str)
            or not re.fullmatch(r"[a-f0-9]{64}", request[k])
            for k in ("image_sha256", "pixel_sha256")
        )
        or not isinstance(request["image_path"], str)
        or len(request["image_path"]) > 2048
    ):
        raise ValueError("Invalid auxiliary OCR request identity")
    path = Path(request["image_path"])
    if (
        not path.is_absolute()
        or path.parent != root
        or any(p.is_symlink() for p in (path, *path.parents))
    ):
        raise ValueError("Auxiliary OCR input is outside the owned row workspace")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError("Auxiliary OCR row is unavailable") from exc
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or not 0 < info.st_size <= MAX_FILE_BYTES
        ):
            raise ValueError("Auxiliary OCR row file exceeds its ownership/size limit")
        payload = stream.read(MAX_FILE_BYTES + 1)
    if (
        len(payload) != info.st_size
        or hashlib.sha256(payload).hexdigest() != request["image_sha256"]
    ):
        raise ValueError("Auxiliary OCR row file changed")
    with Image.open(io.BytesIO(payload)) as source:
        if (
            source.format != "PNG"
            or source.mode != "RGB"
            or source.height > 256
            or source.width > 4096
            or source.height * source.width > MAX_PIXELS
        ):
            raise ValueError("Auxiliary OCR input is not the original bounded RGB row")
        image = np.asarray(source)
    if (
        request["shape"] != list(image.shape)
        or frame_digest(image) != request["pixel_sha256"]
    ):
        raise ValueError("Auxiliary OCR pixel identity differs")
    return image


def validate_reply(reply: dict, request: dict) -> dict:
    if (
        not isinstance(reply, dict)
        or set(reply) != REPLY_FIELDS
        or reply["status"] != "observed"
        or reply["device"] != "cpu"
        or reply["confidence_kind"] != "uncalibrated_model"
        or any(
            reply[key] != request[key]
            for key in ("id", "image_sha256", "pixel_sha256", "model_fingerprint")
        )
        or not isinstance(reply["text"], str)
        or len(reply["text"]) > 4096
        or any(ord(c) < 32 or ord(c) == 127 for c in reply["text"])
        or any(
            type(reply[key]) not in {int, float}
            or not 0 <= reply[key] <= (1 if key == "confidence" else MAX_RSS_MB)
            or not math.isfinite(reply[key])
            for key in ("confidence", "peak_rss_mb")
        )
        or not 0 <= reply["confidence"] <= 1
        or not 0 < reply["peak_rss_mb"] <= MAX_RSS_MB
    ):
        raise ValueError("Auxiliary OCR returned an invalid or unowned observation")
    return dict(reply)
