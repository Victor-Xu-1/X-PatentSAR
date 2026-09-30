#!/usr/bin/env python3
"""Persistent DECIMER JSONL worker.

The single-image wrapper is reliable but reloads TensorFlow/DECIMER for every
structure.  This worker keeps DECIMER loaded and processes one JSON request per
line on stdin:

    {"id": "1", "image_path": "/path/to/structure.png"}

It returns one JSON object per line on stdout and keeps stderr available for
TensorFlow diagnostics.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[3]))
from patent_sar_extractor.core.runtime_env import build_gpu_env  # noqa: E402

os.environ.update(build_gpu_env(python_path=sys.executable))


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> None:
    try:
        from DECIMER import predict_SMILES
    except Exception as exc:
        _emit({"status": "error", "error": f"DECIMER import failed: {exc}"})
        sys.exit(1)

    _emit({"status": "ready"})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "__quit__":
            break
        try:
            request = json.loads(line)
            request_id = request.get("id")
            image_path = str(request.get("image_path") or "")
            if not os.path.isfile(image_path):
                _emit({
                    "id": request_id,
                    "status": "error",
                    "error": f"Image not found: {image_path}",
                })
                continue
            start = time.time()
            smiles = predict_SMILES(image_path)
            elapsed = round(time.time() - start, 3)
            if smiles and isinstance(smiles, str) and smiles.strip():
                _emit({
                    "id": request_id,
                    "status": "success",
                    "smiles": smiles.strip(),
                    "elapsed_sec": elapsed,
                })
            else:
                _emit({
                    "id": request_id,
                    "status": "error",
                    "error": "DECIMER returned empty SMILES",
                    "elapsed_sec": elapsed,
                })
        except Exception as exc:
            _emit({
                "id": request.get("id") if isinstance(locals().get("request"), dict) else None,
                "status": "error",
                "error": f"DECIMER exception: {exc}",
            })


if __name__ == "__main__":
    main()
