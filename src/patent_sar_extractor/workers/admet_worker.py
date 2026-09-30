"""One-shot ADMET-AI 2.0.1 CPU inference; no reference molecules or HTTP server."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
import json
import math
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
from patent_sar_extractor.workers.analysis_protocol import (  # noqa: E402
    ADMET_BUNDLE_SHA256,
    ADMET_VERSION,
    emit,
    prepare,
    read_request,
)


def _model_metadata(root: Path) -> dict[str, dict[str, str]]:
    """Recheck bytes before any checkpoint deserialization, not only at cache lookup."""
    paths = [
        "admet.csv",
        *(
            f"models/admet_{kind}/model_{i}.pt"
            for kind in ("classification", "regression")
            for i in range(5)
        ),
    ]
    entries = []
    metadata = b""
    for relative in sorted(paths):
        path = root / relative
        if root.is_symlink() or any(
            p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)
        ):
            raise ValueError("Unsafe model path")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if os.fstat(stream.fileno()).st_size > 32 * 1024 * 1024:
                raise ValueError("Model file too large")
            data = stream.read(32 * 1024 * 1024 + 1)
        entries.append(
            {
                "path": relative,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        if relative == "admet.csv":
            metadata = data
    digest = hashlib.sha256(
        json.dumps(
            entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    if digest != ADMET_BUNDLE_SHA256:
        raise ValueError("Model fingerprint differs")
    return {
        row["id"]: row for row in csv.DictReader(io.StringIO(metadata.decode("utf-8")))
    }


def _runtime() -> dict[str, str]:
    versions = {
        name: importlib.metadata.version(name)
        for name in ("admet-ai", "chemprop", "torch", "rdkit", "numpy", "lightning")
    }
    if versions["admet-ai"] != ADMET_VERSION or not versions["chemprop"].startswith(
        "2."
    ):
        raise ImportError("ADMET-AI 2.0.1 / Chemprop 2 required")
    import torch
    from admet_ai import ADMETModel  # noqa: F401

    if torch.version.cuda is not None or torch.cuda.is_available():
        raise ImportError("A CPU-only Torch runtime is required")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    return versions


def predict(request: dict[str, object]) -> dict[str, object]:
    versions = _runtime()
    if request == {"mode": "probe"}:
        return {"versions": versions}
    if (
        set(request) != {"mode", "smiles", "model_dir", "model_sha256"}
        or request["mode"] != "predict"
    ):
        raise ValueError("Invalid inference request")
    if request["model_sha256"] != ADMET_BUNDLE_SHA256:
        raise ValueError("Unexpected model identity")
    values = request["smiles"]
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= 50
        or any(
            not isinstance(s, str)
            or not 1 <= len(s) <= 2048
            or any(c.isspace() for c in s)
            for s in values
        )
    ):
        raise ValueError("Invalid molecules")
    from rdkit import Chem

    for value in values:
        molecule = Chem.MolFromSmiles(value)
        if (
            molecule is None
            or not 1 <= molecule.GetNumAtoms() <= 256
            or any(
                a.HasQuery() or a.GetAtomicNum() == 0
                for a in (
                    molecule.GetAtomWithIdx(i) for i in range(molecule.GetNumAtoms())
                )
            )
        ):
            raise ValueError("Invalid molecules")
    root = Path(str(request["model_dir"]))
    metadata = _model_metadata(root)
    from admet_ai import ADMETModel

    model = ADMETModel(
        models_dir=root / "models",
        include_physchem=True,
        drugbank_path=None,
        num_workers=0,
    )
    if model.device != "cpu" or model.drugbank is not None or model.num_ensembles != 2:
        raise ValueError("Unexpected inference configuration")
    frame = model.predict(smiles=values)
    if list(frame.index) != values or set(frame.columns) != set(metadata):
        raise ValueError("Prediction identities or endpoints differ")
    predictions = []
    for index, smiles in enumerate(values):
        properties = []
        for key, value in frame.iloc[index].items():
            row = metadata[str(key)]
            number = float(value)
            probability = row["task_type"] == "classification"
            if not math.isfinite(number) or (probability and not 0 <= number <= 1):
                raise ValueError("Nonfinite or invalid probability")
            unit = "probability [0,1]" if probability else row["units"]
            properties.append(
                {
                    "key": str(key),
                    "label": row["name"],
                    "value": number,
                    "unit": "dimensionless" if unit == "-" else unit,
                    "kind": "descriptor"
                    if row["category"] == "Physicochemical"
                    else "prediction",
                }
            )
        predictions.append({"smiles": smiles, "properties": properties})
    return {
        "engine": {
            "name": "ADMET-AI",
            "version": ADMET_VERSION,
            "model_sha256": ADMET_BUNDLE_SHA256,
        },
        "predictions": predictions,
        "versions": versions,
    }


def main() -> None:
    output = prepare()
    try:
        result = predict(read_request())
    except (ImportError, importlib.metadata.PackageNotFoundError):
        emit(output, {"ok": False, "code": "runtime_unavailable"})
    except Exception as exc:
        # No molecules, local paths, model logs, credentials or tracebacks in the protocol.
        print(f"ADMET analysis failed type={type(exc).__name__}", file=sys.stderr)
        emit(output, {"ok": False, "code": "inference_failed"})
    else:
        emit(output, {"ok": True, "result": result})
    finally:
        output.close()


if __name__ == "__main__":
    main()
