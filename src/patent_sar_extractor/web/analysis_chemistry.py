"""Bounded RDKit validation shared by inputs, OCSR QC and cache reads."""

from __future__ import annotations

import math
from importlib.metadata import version

from rdkit import Chem, rdBase
from rdkit.Chem import rdMolDescriptors

from patent_sar_extractor.core.ocsr.smiles_qc import (
    COMMON_FINAL_PRODUCT_ELEMENTS,
    qc_smiles,
)

from .errors import WebError

MAX_SMILES = 2048
MAX_ATOMS = 256


def canonical_smiles(value: str) -> str:
    """Never discard fragments, query atoms, bad molecules or stereochemistry."""
    if not isinstance(value, str):
        raise WebError(422, "invalid_smiles", "SMILES must be a string.")
    value = value.strip()
    if (
        not value
        or len(value) > MAX_SMILES
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise WebError(
            422,
            "invalid_smiles",
            "Provide a bounded SMILES without titles or control characters.",
        )
    with rdBase.BlockLogs():
        try:
            molecule = Chem.MolFromSmiles(value)
        except (ValueError, RuntimeError) as exc:
            raise WebError(
                422, "invalid_smiles", "SMILES could not be parsed and sanitized."
            ) from exc
    if molecule is None:
        raise WebError(
            422, "invalid_smiles", "SMILES could not be parsed and sanitized."
        )
    if not 1 <= molecule.GetNumAtoms() <= MAX_ATOMS or molecule.GetNumHeavyAtoms() == 0:
        raise WebError(
            422,
            "molecule_limit",
            "A molecule must have heavy atoms and at most 256 atoms.",
        )
    if any(
        a.HasQuery()
        or a.GetAtomicNum() == 0
        or a.GetSymbol() not in COMMON_FINAL_PRODUCT_ELEMENTS
        for a in molecule.GetAtoms()
    ):
        raise WebError(
            422,
            "unsupported_molecule",
            "Query, wildcard or unsupported-element molecules require manual review.",
        )
    if not math.isfinite(rdMolDescriptors.CalcExactMolWt(molecule)):
        raise WebError(422, "invalid_smiles", "Molecular descriptor is not finite.")
    canonical = Chem.MolToSmiles(molecule, isomericSmiles=True)
    if len(canonical) > MAX_SMILES:
        raise WebError(422, "molecule_limit", "Canonical SMILES exceeds its limit.")
    return str(canonical)


def validate_batch(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= 50:
        raise WebError(422, "molecule_limit", "Provide 1–50 valid SMILES.")
    return [canonical_smiles(value) for value in values]


def recognized_smiles(raw: object) -> str | None:
    """The existing production QC is necessary, but this is still only a review result."""
    if not isinstance(raw, str) or len(raw) > MAX_SMILES:
        return None
    try:
        canonical = canonical_smiles(raw)
    except WebError:
        return None
    with rdBase.BlockLogs():
        qc = qc_smiles(raw)
    if qc.get("quality_flag") != "ok" or qc.get("rdkit_valid") is not True:
        return None
    if (
        not qc.get("canonical_smiles")
        or canonical_smiles(qc["canonical_smiles"]) != canonical
    ):
        return None
    return canonical


def chemistry_identity() -> str:
    return f"rdkit:{version('rdkit')}:analysis-qc-1:max-atoms-{MAX_ATOMS}"
