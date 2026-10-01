#!/usr/bin/env python3
"""Bounded offline printed-model JSONL worker in the Python 3.10 boundary."""

import json
import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[3]))
from patent_sar_extractor.core.ocsr.model_identity import (
    printed_model_identity,  # noqa: E402
)


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def main() -> None:
    try:
        identity = printed_model_identity()
        if "--identity" in sys.argv:
            _emit(identity)
            return
        from patent_sar_extractor.core.ocsr.printed_model import PrintedDecimerModel

        model = PrintedDecimerModel(identity)
        _emit(
            {
                "status": "ready",
                "identity": identity,
                "device": model.device,
                "peak_rss_mb": model.peak_rss_mb,
            }
        )
    except Exception as exc:
        _emit({"status": "error", "error": f"DECIMER startup failed: {exc}"})
        raise SystemExit(1) from exc
    while True:
        line = sys.stdin.buffer.readline(4097)
        if not line:
            return
        if len(line) > 4096 or not line.endswith(b"\n"):
            _emit({"status": "error", "error": "Invalid bounded OCSR request"})
            raise SystemExit(1)
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) != {"id", "image_path"}:
                raise ValueError("OCSR request fields are invalid")
            request_id = request["id"]
            if not isinstance(request_id, str) or len(request_id) != 32:
                raise ValueError("OCSR request ID is invalid")
            image = request["image_path"]
            if (
                not isinstance(image, str)
                or len(image) > 2048
                or not os.path.isfile(image)
            ):
                raise ValueError("OCSR input image is missing or invalid")
            started = time.monotonic()
            prediction = model.predict(image)
            _emit(
                {
                    "id": request_id,
                    "status": "success",
                    **prediction,
                    "elapsed_sec": round(time.monotonic() - started, 3),
                }
            )
        except Exception as exc:
            _emit(
                {
                    "id": request_id,
                    "status": "error",
                    "error": f"DECIMER prediction failed: {exc}",
                }
            )


if __name__ == "__main__":
    main()
