"""Explicit real-SDK equivalence/resource probe over existing private observations.

Run in the scientific Python 3.10 boundary; output belongs outside the repository.
Comparing a stored raw string is regression evidence, not original-graph truth.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from patent_sar_extractor.artifact_io import write_json_atomic  # noqa: E402
from patent_sar_extractor.core.ocsr.model_identity import (
    printed_model_identity,  # noqa: E402
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", choices=("printed", "upstream"), default="printed")
    parser.add_argument("--limit", type=int, default=6)
    arguments = parser.parse_args()
    if not 1 <= arguments.limit <= 500:
        parser.error("limit must be between 1 and 500")
    if arguments.observations.stat().st_size > 64 * 1024 * 1024:
        parser.error("observations exceed the size limit")
    payload = json.loads(arguments.observations.read_text(encoding="utf-8"))
    rows = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        parser.error("requires an existing recorded SMILES artifact")
    identity = printed_model_identity()
    os.environ["PATENTSAR_DECIMER_ENABLE_GPU"] = "0"
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    started = time.monotonic()
    if arguments.adapter == "upstream":
        # This explicit diagnostic is never a fallback in the product chain.
        import tensorflow as tf

        tf.config.set_visible_devices([], "GPU")
        from DECIMER import predict_SMILES

        predictor = predict_SMILES
    else:
        from patent_sar_extractor.core.ocsr.printed_model import PrintedDecimerModel

        model = PrintedDecimerModel(identity)

        def predictor(path):
            return model.predict(path)["smiles"]

    loaded = time.monotonic()
    comparisons = []
    for row in rows[: arguments.limit]:
        image = row.get("ocsr_structure_image")
        if not isinstance(image, str) or not Path(image).is_file():
            raise ValueError("Recorded model input image is unavailable")
        before = time.monotonic()
        actual = predictor(image)
        comparisons.append(
            {
                "compound_id": row.get("cpd_id"),
                "raw_smiles": actual,
                "matches_previous_raw": actual == row.get("engine_raw_smiles"),
                "inference_seconds": round(time.monotonic() - before, 3),
            }
        )
    result = {
        "adapter": arguments.adapter,
        "fingerprint": identity["fingerprint"],
        "versions": identity["versions"],
        "load_seconds": round(loaded - started, 3),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "peak_rss_mb": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2
        ),
        "comparisons": comparisons,
        "all_raw_equal": all(row["matches_previous_raw"] for row in comparisons),
    }
    write_json_atomic(arguments.output, result)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "comparisons"}
        )
    )
    if not result["all_raw_equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
