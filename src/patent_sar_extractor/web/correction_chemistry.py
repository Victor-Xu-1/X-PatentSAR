"""Bounded MDL validation; no graph repair, stereo guessing or source rewriting."""

from __future__ import annotations

import math
import unicodedata
from functools import lru_cache

from rdkit import Chem, rdBase

from patent_sar_extractor.core.ocsr.smiles_qc import COMMON_FINAL_PRODUCT_ELEMENTS

from .analysis_chemistry import MAX_ATOMS, canonical_smiles
from .errors import WebError

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


def _counts(text: str) -> None:
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
    if not 1 <= atoms <= MAX_ATOMS or not 0 <= bonds <= 4096:
        raise ValueError("Molfile atom/bond counts are excessive")


@lru_cache(maxsize=32)
def _molfile_graph(text: str) -> str:
    # At most 4 MiB of bounded input strings; retain no RDKit objects or source data.
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
                for atom in molecule.GetAtoms()
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
                or bond.GetStereo() == Chem.BondStereo.STEREOANY
                for bond in molecule.GetBonds()
            ):
                raise ValueError(
                    "Query/unsupported bonds or unspecified encoded stereo are not supported"
                )
            if any(
                group.GetGroupType() != Chem.StereoGroupType.STEREO_ABSOLUTE
                for group in molecule.GetStereoGroups()
            ):
                raise ValueError(
                    "Relative/enhanced stereo cannot be represented by the supplied SMILES"
                )
            for conformer in molecule.GetConformers():
                for index in range(molecule.GetNumAtoms()):
                    position = conformer.GetAtomPosition(index)
                    if not all(
                        math.isfinite(value)
                        for value in (position.x, position.y, position.z)
                    ):
                        raise ValueError("Molfile coordinates must be finite")
            stereo = {
                atom.GetIdx()
                for atom in molecule.GetAtoms()
                if atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED
            }
            Chem.SanitizeMol(molecule)
            Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
            if any(
                molecule.GetAtomWithIdx(index).GetChiralTag()
                == Chem.ChiralType.CHI_UNSPECIFIED
                for index in stereo
            ):
                raise ValueError("Sanitization would discard encoded stereochemistry")
            molecule = Chem.RemoveHs(molecule)
            return canonical_smiles(Chem.MolToSmiles(molecule, isomericSmiles=True))
        except (RuntimeError, ValueError, WebError) as exc:
            raise ValueError(
                "Molfile is invalid, unsupported or cannot retain exact stereochemistry"
            ) from exc


def validate_structure(molfile: str | None, smiles: str | None) -> None:
    if molfile is None:
        return
    if smiles is None:
        raise ValueError("A drawn structure requires its exact SMILES")
    try:
        identity = canonical_smiles(smiles)
    except WebError as exc:
        raise ValueError("Drawn structure SMILES is invalid") from exc
    if _molfile_graph(molfile) != identity:
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
