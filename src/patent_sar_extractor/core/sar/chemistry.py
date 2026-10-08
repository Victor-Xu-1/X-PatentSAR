"""Validate SAR inputs and bind immutable atom order separately from identity."""

from __future__ import annotations

import hashlib
from typing import Any

from rdkit import Chem, rdBase

from .errors import SARInputError
from .molecules import chemical_identity, depict, read_molfile, read_smiles


def prepare_structure(smiles: str | None, molfile: str | None = None) -> dict[str, Any]:
    """Retain raw SMILES; retain provided Molfile exactly, or create it once.

    graph_sha256 hashes exact UTF-8 Molfile bytes (including atom order).
    chemical_sha256 hashes canonical complete isomeric identity only and is an
    internal importer grouping key, not a public DTO or scientific acceptance.
    Missing/unsupported/inconsistent inputs have no chemical identity.
    """
    result: dict[str, Any] = {
        "smiles": smiles,
        "molfile": None,
        "graph_sha256": None,
        "chemical_sha256": None,
        "eligible": False,
        "issues": [],
    }
    try:
        mol = read_smiles(smiles)
        identity = chemical_identity(mol)
        if molfile is None:
            depict(mol)
            with rdBase.BlockLogs():
                block = Chem.MolToMolBlock(mol, includeStereo=True, kekulize=True)
        else:
            block = molfile
        stored = read_molfile(block)
        if chemical_identity(stored) != identity:
            raise SARInputError("smiles_molfile_mismatch")
        result.update(
            molfile=block,
            graph_sha256=hashlib.sha256(block.encode("utf-8")).hexdigest(),
            chemical_sha256=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            eligible=True,
        )
    except SARInputError as exc:
        result["issues"] = [exc.code]
    except (ValueError, RuntimeError, OverflowError, UnicodeError):
        result["issues"] = ["structure_preparation_failed"]
    return result
