"""Deterministic five-property calculations, independent of neural predictions."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.metadata import version

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors

from .analysis_chemistry import canonical_smiles, chemistry_identity
from .prediction_models import METRIC_KEYS, METRIC_SPECS, PredictionMetric

DESCRIPTOR_KEYS = METRIC_KEYS[:5]
ALGORITHMS = (
    "Descriptors.MolWt",
    "Crippen.MolLogP",
    "rdMolDescriptors.CalcTPSA",
    "Lipinski.NumHDonors",
    "Lipinski.NumHAcceptors",
)


@lru_cache(maxsize=1)
def descriptor_epoch() -> str:
    return hashlib.sha256(
        json.dumps(
            [
                1,
                chemistry_identity(),
                ALGORITHMS,
                [METRIC_SPECS[k] for k in DESCRIPTOR_KEYS],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def _rdkit_version() -> str:
    return version("rdkit")


def descriptor_engine() -> dict[str, str]:
    return {
        "name": "RDKit",
        "version": _rdkit_version(),
        "algorithm_sha256": descriptor_epoch(),
    }


def compute_descriptors(smiles: str) -> list[PredictionMetric]:
    """Preserve isotopes, charges, components and stereo in a validated molecule."""
    molecule = Chem.MolFromSmiles(canonical_smiles(smiles))
    modules = {
        "Descriptors": Descriptors,
        "Crippen": Crippen,
        "rdMolDescriptors": rdMolDescriptors,
        "Lipinski": Lipinski,
    }
    # RDKit exposes several registered descriptors dynamically; its stubs do
    # not enumerate them. The fixed reviewed algorithm names remain authority.
    calculators = tuple(
        getattr(modules[reference.split(".")[0]], reference.split(".")[1])
        for reference in ALGORITHMS
    )
    result = []
    for key, calculate in zip(DESCRIPTOR_KEYS, calculators):
        label, unit, _kind = METRIC_SPECS[key]
        result.append(
            PredictionMetric(
                key=key,
                label=label,
                unit=unit,
                kind="descriptor",
                value=float(calculate(molecule)),
            )
        )
    return result
