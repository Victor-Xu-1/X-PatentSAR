"""Bounded offline JSONL worker; only the constrained post-primary pass calls it."""

import json
import os
import runpy
import socket
import sys
import time
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "worker_bootstrap.py"),
    run_name="__main__",
)
from patent_sar_extractor.core.ocsr.molscribe_identity import (
    molscribe_identity,
)
from patent_sar_extractor.workers.analysis_protocol import _network_denied


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def main() -> None:
    # Native inference cannot download or disclose crops, regardless of parent
    # API credentials or proxy settings. Provisioning is a separate consented action.
    socket.socket.connect = _network_denied
    socket.socket.connect_ex = _network_denied
    socket.create_connection = _network_denied
    os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
    # Exact model hashes are verified before either native import or deserialization.
    identity = molscribe_identity()
    if "--identity" in sys.argv:
        emit(identity)
        return
    from patent_sar_extractor.core.ocsr.molscribe_model import PinnedMolScribeModel

    model = PinnedMolScribeModel(identity)
    emit({"status": "ready", "identity": identity})
    for _ in range(8):
        line = sys.stdin.buffer.readline(4097)
        if not line:
            return
        request = json.loads(line)
        if (
            len(line) > 4096
            or not line.endswith(b"\n")
            or not isinstance(request, dict)
            or set(request) != {"id", "image_path"}
        ):
            raise ValueError("Invalid bounded rescue request")
        request_id, image = request["id"], request["image_path"]
        if (
            not isinstance(request_id, str)
            or len(request_id) != 32
            or not isinstance(image, str)
            or len(image) > 2048
            or not os.path.isfile(image)
        ):
            raise ValueError("Rescue input identity is invalid")
        started = time.monotonic()
        output = model.predict(image)
        emit(
            {
                "id": request_id,
                "status": "success",
                **output,
                "elapsed_sec": time.monotonic() - started,
            }
        )


if __name__ == "__main__":
    main()
