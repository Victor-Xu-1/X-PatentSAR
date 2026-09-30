#!/usr/bin/env python3
"""DECIMER wrapper script for subprocess invocation.

This script runs inside the `decimer` conda environment and is called
by `DECIMEREngine` via subprocess. It accepts an image path, runs
DECIMER prediction, and outputs JSON to stdout.

Usage:
    /path/to/decimer/env/python wrapper_decimer.py <image_path>

Output (JSON on stdout):
    {"status": "success", "smiles": "C1=CC=...", "elapsed_sec": 7.8}
    {"status": "error", "error": "error message"}
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[3]))
from patent_sar_extractor.core.runtime_env import build_gpu_env  # noqa: E402

os.environ.update(build_gpu_env(python_path=sys.executable))


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "error": "Usage: wrapper_decimer.py <image_path>"}))
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        print(json.dumps({"status": "error", "error": f"Image not found: {image_path}"}))
        sys.exit(1)

    try:
        from DECIMER import predict_SMILES

        start = time.time()
        smiles = predict_SMILES(image_path)
        elapsed = time.time() - start

        if smiles and isinstance(smiles, str) and smiles.strip():
            print(json.dumps({
                "status": "success",
                "smiles": smiles.strip(),
                "elapsed_sec": round(elapsed, 3),
            }))
        else:
            print(json.dumps({
                "status": "error",
                "error": "DECIMER returned empty SMILES",
                "elapsed_sec": round(elapsed, 3),
            }))

    except Exception as e:
        print(json.dumps({"status": "error", "error": f"DECIMER exception: {str(e)}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
