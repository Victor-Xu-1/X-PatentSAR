"""Content/version-bound SAR worker identity, independent of product PR releases."""

from __future__ import annotations

import hashlib
from importlib.metadata import version
from pathlib import Path

from ...contracts import SAR_ENGINE_NAME, SAR_ENGINE_VERSION
from ...core.sar import chemistry
from ...workers import sar_worker
from ..storage import encode


def engine_identity() -> str:
    root = Path(chemistry.__file__).parent
    files = sorted(root.glob("*.py")) + [Path(sar_worker.__file__)]
    files += sorted(Path(sar_worker.__file__).parent.glob("study_*.py"))
    # Both modes use source-bound descriptors and shared chemistry primitives;
    # scientific checkpoints cannot survive a change to those computations.
    from .. import descriptor_fields, lead_chemistry, lead_endpoints

    files += [
        Path(module.__file__)
        for module in (descriptor_fields, lead_chemistry, lead_endpoints)
    ]
    files += [
        Path(__file__).with_name(name) for name in ("models.py", "study_models.py")
    ]
    if len(files) > 64 or any(path.stat().st_size > 256 * 1024 for path in files):
        raise ValueError("SAR code inventory exceeds its bound")
    return hashlib.sha256(
        encode(
            [
                SAR_ENGINE_NAME,
                SAR_ENGINE_VERSION,
                version("rdkit"),
                [
                    (path.name, hashlib.sha256(path.read_bytes()).hexdigest())
                    for path in files
                ],
            ]
        ).encode()
    ).hexdigest()
