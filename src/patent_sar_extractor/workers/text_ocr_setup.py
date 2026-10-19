"""Managed ordinary-text assets/probes reuse the one literal-row model adapter."""

import hashlib
import os
import stat
import sys
import tempfile
import uuid
from pathlib import Path

from patent_sar_extractor.core.text_ocr.identity import (
    model_files,
    recipe,
    runtime_inventory,
    text_identity,
)

from .environment_assets import download


def _copy_model(asset, target, item, cancel):
    if cancel.is_set():
        raise InterruptedError("Auxiliary text model installation cancelled")
    fd = os.open(asset, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != item["size"]:
            raise ValueError("Auxiliary model asset size/type differs")
        digest, received = hashlib.sha256(), 0
        with target.open("xb") as output:
            while chunk := source.read(1024 * 1024):
                if cancel.is_set():
                    raise InterruptedError(
                        "Auxiliary text model installation cancelled"
                    )
                received += len(chunk)
                if received > item["size"]:
                    raise ValueError("Auxiliary model asset exceeded its copy bound")
                digest.update(chunk)
                output.write(chunk)
        if cancel.is_set():
            raise InterruptedError("Auxiliary text model installation cancelled")
        if received != item["size"] or digest.hexdigest() != item["sha256"]:
            raise ValueError("Auxiliary model asset content changed during copying")


def install_text_models(prefix, cache, cancel, progress):
    spec = recipe()
    base = (
        "https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec/resolve/"
        + spec["model_revision"]
        + "/"
    )
    root = prefix / "models"
    root.mkdir(mode=0o700)
    for item in spec["models"]:
        if cancel.is_set():
            raise InterruptedError("Auxiliary text model installation cancelled")
        asset = download(
            base + item["file"],
            cache,
            size=item["size"],
            sha256=item["sha256"],
            cancel=cancel,
            progress=progress,
        )
        _copy_model(asset, root / item["file"], item, cancel)
    model_files(root, spec)
    return root


def probe_text_runtime(request, result):
    spec = recipe()
    versions, _ = runtime_inventory(spec)
    import paddle
    from paddleocr import TextRecognition

    checks = result["checks"]
    checks.extend(
        [
            {
                "name": "python",
                "ok": sys.version_info[:3] == (3, 10, 20),
                "message": "Actual pinned isolated Python 3.10.20",
            },
            {
                "name": "reviewed_sdk",
                "ok": callable(TextRecognition),
                "message": "Reviewed SDK inventory, versions and native interface verified",
            },
            {
                "name": "cpu_only",
                "ok": not paddle.is_compiled_with_cuda(),
                "message": "Actual CPU-only Paddle build; not a local LLM",
            },
        ]
    )
    if request["role"] == "text-ocr-models":
        identity = text_identity(Path(str(request["model_root"])))
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        from patent_sar_extractor.core.text_ocr.model import LiteralTextModel
        from patent_sar_extractor.core.text_ocr.protocol import frame_digest

        with tempfile.TemporaryDirectory(prefix="text-ocr-probe-") as temporary:
            root = Path(temporary)
            image = Image.new("RGB", (300, 90), "white")
            ImageDraw.Draw(image).text(
                (15, 18), "OCR 123", fill="black", font=ImageFont.load_default(size=36)
            )
            path = root / "row.png"
            image.save(path, format="PNG")
            pixels = np.asarray(image)
            packet = {
                "id": uuid.uuid4().hex,
                "image_path": str(path),
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "pixel_sha256": frame_digest(pixels),
                "shape": list(pixels.shape),
                "model_fingerprint": identity["fingerprint"],
            }
            observed = LiteralTextModel(identity, root).observe(packet)
        checks.append(
            {
                "name": "models_loaded",
                "ok": bool(observed["text"].strip()),
                "message": "Actual offline model load and generated row; not accuracy acceptance",
            }
        )
        result["model_fingerprint"] = identity["fingerprint"]
    result.update(
        ok=all(check["ok"] for check in checks),
        version=versions["paddleocr"],
        versions=versions,
    )
    return result
