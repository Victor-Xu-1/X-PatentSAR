"""Truthful native runtime/model probes for the single local rescue adapter."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

from patent_sar_extractor.core.ocsr.molscribe_identity import (
    molscribe_identity,
    rescue_recipe,
)


def probe_local_rescue(request: dict, result: dict) -> dict:
    recipe = rescue_recipe()
    found = {name: importlib.metadata.version(name) for name in recipe["distributions"]}
    import torch
    from molscribe import MolScribe

    checks = result["checks"]
    checks.append(
        {
            "name": "python",
            "ok": sys.version_info[:3] == (3, 10, 20),
            "message": "Actual pinned Python 3.10.20",
        }
    )
    checks.append(
        {
            "name": "versions",
            "ok": found == recipe["distributions"],
            "message": "Actual reviewed local rescue distribution versions",
        }
    )
    checks.append(
        {
            "name": "cpu_only",
            "ok": torch.version.cuda is None and not torch.cuda.is_available(),
            "message": "Actual native CPU-only Torch build",
        }
    )
    checks.append(
        {
            "name": "sdk",
            "ok": callable(MolScribe.predict_image_file),
            "message": "Native SDK interface imports successfully",
        }
    )
    result["versions"] = found
    if request["role"] == "molscribe-models":
        from patent_sar_extractor.core.ocsr.molscribe_model import PinnedMolScribeModel

        identity = molscribe_identity(Path(str(request["model_root"])))
        model = PinnedMolScribeModel(identity)
        checks.append(
            {
                "name": "models_loaded",
                "ok": model.device == "cpu",
                "message": "Hash-verified tensor-only actual model load; not accuracy acceptance",
            }
        )
        result["model_fingerprint"] = identity["fingerprint"]
    result["ok"] = all(check["ok"] for check in checks)
    result["version"] = found["MolScribe"]
    return result
