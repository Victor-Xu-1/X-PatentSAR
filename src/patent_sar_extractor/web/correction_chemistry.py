"""Bounded MDL validation; no graph repair, stereo guessing or source rewriting."""

from __future__ import annotations

import math
import unicodedata
from functools import lru_cache

from rdkit import Chem, rdBase

from patent_sar_extractor.core.ocsr.smiles_qc import COMMON_FINAL_PRODUCT_ELEMENTS

from .analysis_chemistry import MAX_ATOMS, canonical_smiles
from .errors import WebError
from .molecular_stereo import (
    atoms,
    bonds,
    comparable_groups,
    stereo_snapshot,
    unknown_bonds,
    unresolved_stereo_key,
    validate_stereo_encoding,
)

MAX_MOLFILE_BYTES = 128 * 1024


def validate_molfile_text(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_MOLFILE_BYTES
        or any(
            unicodedata.category(char).startswith("C") and char not in "\n\r\t"
            for char in value
        )
    ):
        raise ValueError("Molfile text is empty, invalid or excessive")
    try:
        if len(value.encode("utf-8")) > MAX_MOLFILE_BYTES:
            raise ValueError("Molfile exceeds 128 KiB")
    except UnicodeError as exc:
        raise ValueError("Molfile must be valid UTF-8") from exc
    return value


def same_graph(left: str | None, right: str | None) -> bool:
    # Exact resets may retain rejected original strings, without promoting them.
    if left == right:
        return True
    if left is None or right is None:
        return False
    try:
        return canonical_smiles(left) == canonical_smiles(right)
    except WebError:
        return False


def _counts(text: str, *, allow_empty: bool = False) -> tuple[int, int]:
    lines = text.rstrip().splitlines()
    if (
        len(lines) < 5
        or lines[-1].strip() != "M  END"
        or any("$$$$" in line for line in lines)
        or sum(line.strip() == "M  END" for line in lines[4:]) != 1
    ):
        raise ValueError(
            "Provide one complete MDL molfile, not an SDF or trailing data"
        )
    header = lines[3].rstrip()
    try:
        if header.endswith("V2000"):
            atoms, bonds = int(header[:3]), int(header[3:6])
        elif header.endswith("V3000"):
            counts = next(
                line.split() for line in lines[4:] if line.startswith("M  V30 COUNTS ")
            )
            atoms, bonds = int(counts[3]), int(counts[4])
        else:
            raise ValueError("Only V2000 and V3000 are supported")
    except (ValueError, IndexError, StopIteration) as exc:
        raise ValueError("MDL counts/version header is invalid") from exc
    if not int(not allow_empty) <= atoms <= MAX_ATOMS or not 0 <= bonds <= 4096:
        raise ValueError("Molfile atom/bond counts are excessive")
    return atoms, bonds


def molfile_molecule(text: str) -> Chem.Mol:
    """Strict, fresh drawing molecule; never cache or rewrite RDKit source objects."""
    validate_molfile_text(text)
    _counts(text)
    with rdBase.BlockLogs():
        try:
            molecule = Chem.MolFromMolBlock(
                text, sanitize=False, removeHs=False, strictParsing=True
            )
            if molecule is None or not 1 <= molecule.GetNumAtoms() <= MAX_ATOMS:
                raise ValueError("Molfile cannot be parsed strictly")
            if any(
                atom.HasQuery()
                or atom.GetAtomicNum() == 0
                or atom.GetSymbol() not in COMMON_FINAL_PRODUCT_ELEMENTS
                for atom in atoms(molecule)
            ):
                raise ValueError(
                    "Query, dummy and unsupported atoms are not editable molecules"
                )
            if any(
                bond.HasQuery()
                or bond.GetBondType()
                not in {
                    Chem.BondType.SINGLE,
                    Chem.BondType.DOUBLE,
                    Chem.BondType.TRIPLE,
                    Chem.BondType.AROMATIC,
                }
                for bond in bonds(molecule)
            ):
                raise ValueError("Query/unsupported bonds are not editable molecules")
            validate_stereo_encoding(molecule, text)
            for conformer in molecule.GetConformers():
                for index in range(molecule.GetNumAtoms()):
                    position = conformer.GetAtomPosition(index)
                    if not all(
                        math.isfinite(value)
                        for value in (position.x, position.y, position.z)
                    ):
                        raise ValueError("Molfile coordinates must be finite")
            stereo = stereo_snapshot(molecule)
            groups = comparable_groups(molecule)
            unknown = unknown_bonds(molecule)
            Chem.SanitizeMol(molecule)
            Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
            after = stereo_snapshot(molecule)
            # Sanitization may perceive defined EZ from the supplied coordinates.
            # It must not erase/change anything already encoded, including ANY.
            if (
                not set(stereo[0]).issubset(after[0])
                or not set(stereo[1]).issubset(after[1])
                or groups != comparable_groups(molecule)
                or unknown_bonds(molecule) != unknown
            ):
                raise ValueError("Sanitization would discard encoded stereochemistry")
            return molecule
        except (RuntimeError, ValueError, WebError) as exc:
            raise ValueError(
                "Molfile is invalid, unsupported or cannot retain exact stereochemistry"
            ) from exc


@lru_cache(maxsize=32)
def molfile_representation(text: str) -> tuple[str, str | None]:
    # At most 4 MiB of input strings; no mutable RDKit objects are cached.
    molecule = molfile_molecule(text)
    ambiguity = unresolved_stereo_key(molecule)
    graph = canonical_smiles(
        Chem.MolToSmiles(Chem.RemoveHs(molecule), isomericSmiles=True)
    )
    return graph, ambiguity


def converted_smiles(text: str) -> str | None:
    """The same MDL authority derives editor SMILES; never trust vendor parity.

    Keep exact MDL elsewhere. Explicit unknown bonds govern unspecified centers,
    including native writers' redundant atom parity/ABS collection. No atom,
    isotope, charge, component or definite stereochemistry is repaired/guessed.
    """
    validate_molfile_text(text)
    atoms, bonds = _counts(text, allow_empty=True)
    if atoms == bonds == 0:
        with rdBase.BlockLogs():
            molecule = Chem.MolFromMolBlock(text, removeHs=False, strictParsing=True)
        if molecule is None or molecule.GetNumAtoms() or molecule.GetNumBonds():
            raise ValueError("Empty drawing does not match its atom/bond counts")
        return None
    return molfile_representation(text)[0]


def same_structure(
    left: str | None,
    right: str | None,
    left_molfile: str | None = None,
    right_molfile: str | None = None,
) -> bool:
    if not same_graph(left, right):
        return False
    if left_molfile == right_molfile:
        return True
    left_stereo = molfile_representation(left_molfile)[1] if left_molfile else None
    right_stereo = molfile_representation(right_molfile)[1] if right_molfile else None
    return left_stereo == right_stereo


def validate_structure(molfile: str | None, smiles: str | None) -> None:
    if molfile is None:
        return
    if smiles is None:
        raise ValueError("A drawn structure requires its exact SMILES")
    try:
        identity = canonical_smiles(smiles)
    except WebError as exc:
        raise ValueError("Drawn structure SMILES is invalid") from exc
    if molfile_representation(molfile)[0] != identity:
        raise ValueError(
            "Molfile graph and stereochemistry differ from the supplied SMILES"
        )


def validate_property_basis(
    overrides: object, basis: str | None, smiles: str | None
) -> None:
    if not overrides:
        return
    if smiles is None:
        if basis is not None:
            raise ValueError("Missing SMILES requires a null manual property basis")
        return
    if basis is None:
        raise ValueError("Manual properties require their SMILES basis")
    try:
        if canonical_smiles(basis) != canonical_smiles(smiles):
            raise ValueError("Manual properties refer to a different molecule")
    except WebError as exc:
        raise ValueError("Manual property basis SMILES is invalid") from exc
