"""One-action fixed local rescue assets; no caller URLs or unpinned build inputs."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from patent_sar_extractor.core.ocsr.molscribe_identity import rescue_recipe

from .environment_assets import download


def install_sdk(installer, python, prefix, cache, cancel, progress, command) -> None:
    source = rescue_recipe()["sdk"]
    archive = download(
        source["url"],
        cache,
        size=source["size"],
        sha256=source["sha256"],
        cancel=cancel,
        progress=progress,
    )
    target = prefix / "molscribe-source.zip"
    with archive.open("rb") as stream, target.open("xb") as output:
        shutil.copyfileobj(stream, output)
    # All build inputs (including NumPy/setuptools/wheel) came from the locked
    # runtime recipe. Only this verified upstream archive may be built, offline.
    command(
        [
            installer,
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--no-build-isolation",
            "--offline",
            str(target),
        ]
    )


def install_models(
    prefix: Path, cache: Path, cancel: threading.Event, progress
) -> Path:
    model = rescue_recipe()["model"]
    asset = download(
        model["url"],
        cache,
        size=model["size"],
        sha256=model["sha256"],
        cancel=cancel,
        progress=progress,
    )
    target = prefix / "models"
    target.mkdir(mode=0o700)
    with asset.open("rb") as stream, (target / model["file"]).open("xb") as output:
        while chunk := stream.read(1024 * 1024):
            if cancel.is_set():
                raise InterruptedError("Local rescue installation cancelled")
            output.write(chunk)
    return target
