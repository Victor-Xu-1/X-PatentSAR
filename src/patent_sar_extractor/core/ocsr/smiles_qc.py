"""
SMILES Quality Control module using RDKit.

Validates and standardizes raw SMILES predictions from OCSR engines.
Preserves ALL raw predictions even if RDKit validation fails.
"""

import re
from typing import Optional

COMMON_FINAL_PRODUCT_ELEMENTS = {
    "H",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Na",
    "Mg",
    "Si",
    "P",
    "S",
    "Cl",
    "K",
    "Ca",
    "Br",
    "I",
}


def qc_smiles(raw_smiles: Optional[str]) -> dict:
    """Validate and standardize a raw SMILES string using RDKit.

    Args:
        raw_smiles: Raw SMILES string from an OCSR engine. Can be None or empty.

    Returns:
        dict with the following keys:
            - rdkit_valid (bool): Whether RDKit could parse the SMILES
            - canonical_smiles (str|None): RDKit canonical SMILES
            - isomeric_smiles (str|None): RDKit isomeric SMILES
            - inchikey (str|None): InChIKey
            - mol_formula (str|None): Molecular formula
            - mol_weight (float|None): Molecular weight
            - heavy_atom_count (int): Number of heavy atoms
            - ring_count (int): Number of rings
            - chiral_centers (int): Number of chiral centers
            - has_dummy_atom (bool): Contains dummy/wildcard atoms
            - has_query_atom (bool): Contains query atoms (R, A, Q etc.)
            - suspicious_elements (list[str]): Unusual final-product elements
              that cannot be auto-accepted without corroborating evidence
            - sanitize_error (str|None): RDKit sanitization error message
            - quality_flag (str): Quality classification flag
    """
    result = {
        "rdkit_valid": False,
        "canonical_smiles": None,
        "isomeric_smiles": None,
        "inchikey": None,
        "mol_formula": None,
        "mol_weight": None,
        "heavy_atom_count": 0,
        "ring_count": 0,
        "chiral_centers": 0,
        "has_dummy_atom": False,
        "has_query_atom": False,
        "suspicious_elements": [],
        "sanitize_error": None,
        "quality_flag": "empty_prediction",
    }

    # Empty check
    if not raw_smiles or not raw_smiles.strip():
        result["quality_flag"] = "empty_prediction"
        return result

    raw_smiles = raw_smiles.strip()

    # Check for dummy atoms: * in SMILES
    result["has_dummy_atom"] = _has_dummy_atom(raw_smiles)

    # Check for query/Markush atoms: R, [R], [R1], [R2], A, Q, [A], [Q], M, [M], [1*], etc.
    result["has_query_atom"] = _has_query_atom(raw_smiles)

    # If has dummy or query atoms, still try RDKit but flag accordingly
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors
    except ImportError:
        result["quality_flag"] = "rdkit_not_available"
        return result

    # Try to parse SMILES
    try:
        mol = Chem.MolFromSmiles(raw_smiles)
    except Exception as e:
        result["sanitize_error"] = str(e)
        result["quality_flag"] = "sanitize_failed"
        return result

    if mol is None:
        # RDKit could not parse - check if it's a Markush/query issue
        if result["has_dummy_atom"] or result["has_query_atom"]:
            result["quality_flag"] = "markush_or_query"
        else:
            result["quality_flag"] = "invalid_smiles"
        return result

    # RDKit successfully parsed
    result["rdkit_valid"] = True
    result["suspicious_elements"] = sorted(
        {
            atom.GetSymbol()
            for atom in mol.GetAtoms()
            if atom.GetSymbol() not in COMMON_FINAL_PRODUCT_ELEMENTS
        }
    )

    try:
        result["canonical_smiles"] = Chem.MolToSmiles(mol)
    except Exception as e:
        result["sanitize_error"] = f"canonical_smiles failed: {e}"

    try:
        result["isomeric_smiles"] = Chem.MolToSmiles(mol, isomericSmiles=True)
    except Exception:
        pass  # Non-critical

    try:
        result["inchikey"] = Chem.MolToInchiKey(mol)
    except Exception:
        pass  # Non-critical

    try:
        result["mol_formula"] = rdMolDescriptors.CalcMolFormula(mol)
    except Exception:
        pass  # Non-critical

    try:
        result["mol_weight"] = round(Descriptors.ExactMolWt(mol), 4)
    except Exception:
        pass  # Non-critical

    try:
        result["heavy_atom_count"] = mol.GetNumHeavyAtoms()
    except Exception:
        pass

    try:
        result["ring_count"] = Lipinski.RingCount(mol)
    except Exception:
        pass

    try:
        from rdkit.Chem import FindMolChiralCenters

        chiral_centers = FindMolChiralCenters(mol, includeUnassigned=True)
        result["chiral_centers"] = len(chiral_centers)
    except Exception:
        pass

    # Set quality flag
    if result["has_dummy_atom"] or result["has_query_atom"]:
        result["quality_flag"] = "markush_or_query"
    elif result["suspicious_elements"]:
        result["quality_flag"] = "suspicious_element"
    else:
        result["quality_flag"] = "ok"

    return result


def _has_dummy_atom(smiles: str) -> bool:
    """Check if SMILES contains dummy atoms (*, [#0], etc.)."""
    # Star atoms: * or [#0]
    if "*" in smiles:
        return True
    if "[#0]" in smiles:
        return True
    return False


def _has_query_atom(smiles: str) -> bool:
    """Check if SMILES contains query/Markush atoms.

    Detects patterns like:
    - [R], [R1], [R2], ... (R-group labels)
    - [A], [Q], [M] (any, not-carbon, mixed)
    - [1*], [2*], ... (numbered R-groups)
    - Bare R, A, Q at atom level (less common in valid SMILES)
    """
    # R-group brackets: [R], [R1], [R2], [R3]...
    if re.search(r"\[R\d*\]", smiles):
        return True
    # Query atom brackets: [A], [Q], [M]
    if re.search(r"\[[AQM]\]", smiles):
        return True
    # Numbered star: [1*], [2*], [3*]...
    if re.search(r"\[\d+\*\]", smiles):
        return True
    return False
