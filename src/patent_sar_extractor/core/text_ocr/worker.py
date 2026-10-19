"""Finite offline JSONL text worker; no page parser, selection, or result writer."""

import os
import runpy
import stat
import sys
from pathlib import Path

if sys.path and Path(sys.path[0]).resolve() == Path(__file__).resolve().parent:
    # A standalone script directory must not shadow installed SDK dependencies.
    # First-party modules below are selected by the existing package bootstrap.
    sys.path.pop(0)

runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "worker_bootstrap.py"),
    run_name="__main__",
)
from patent_sar_extractor.core.text_ocr.identity import text_identity
from patent_sar_extractor.core.text_ocr.request_stream import request_packets
from patent_sar_extractor.worker_lifecycle import arm_parent_death
from patent_sar_extractor.workers.analysis_protocol import (
    emit,
    prepare,
)


def main():
    arm_parent_death(int(os.environ.get("PATENTSAR_WORKER_PARENT_PID", "0")))
    output = prepare()
    # These flags only suppress optional SDK discovery; prepare() denies all
    # socket connections independently, even if an SDK ignores its offline flags.
    os.environ.update(
        CUDA_VISIBLE_DEVICES="-1",
        OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2",
        OPENBLAS_NUM_THREADS="2",
        PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True",
        HF_HUB_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        DO_NOT_TRACK="1",
    )
    identity = text_identity(Path(os.environ.get("PATENTSAR_TEXT_OCR_MODEL_DIR", "")))
    if sys.argv[1:] == ["--identity"]:
        emit(output, identity)
        return
    if sys.argv[1:]:
        raise ValueError("Unknown auxiliary text OCR worker operation")
    root = Path(os.environ.get("PATENTSAR_TEXT_OCR_INPUT_ROOT", ""))
    info = root.lstat()
    if (
        not root.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or any(p.is_symlink() for p in (root, *root.parents))
    ):
        raise ValueError("Auxiliary text OCR requires an owned private row workspace")
    from patent_sar_extractor.core.text_ocr.model import LiteralTextModel

    model = LiteralTextModel(identity, root)
    emit(output, {"status": "ready", "identity": identity})
    for request in request_packets(sys.stdin.buffer):
        emit(output, model.observe(request))


if __name__ == "__main__":
    main()
