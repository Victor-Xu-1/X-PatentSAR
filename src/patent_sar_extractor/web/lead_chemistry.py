"""Bounded RDKit-only chemistry, soft desirability and fixed-size fingerprints."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .lead_endpoints import LEAD_ENDPOINTS, validate_endpoints
from .models import Compound
from .prediction_models import METRIC_KEYS
from .property_values import effective_property_values

if TYPE_CHECKING:
    from rdkit.DataStructs.cDataStructs import ExplicitBitVect

# Grouping/weights belong to scoring; the shared reviewed catalog alone owns
# endpoint membership and label direction. Do not duplicate that authority.
RISK_ENDPOINTS = tuple(
    key
    for key, direction in LEAD_ENDPOINTS.items()
    if direction == "lower" and not key.startswith("CYP")
)
ABSORPTION_ENDPOINTS = tuple(
    key for key, direction in LEAD_ENDPOINTS.items() if direction == "higher"
)
CYP_ENDPOINTS = tuple(key for key in LEAD_ENDPOINTS if key.startswith("CYP"))


def validated_endpoints(compound: Compound) -> dict[str, float] | None:
    """Absent/invalid overview is unknown, not zero risk or a model invocation."""
    if compound.admet is None or compound.admet.status != "complete":
        return None
    endpoints = getattr(compound.admet, "endpoints", None)
    if not isinstance(endpoints, dict) or set(endpoints) != set(LEAD_ENDPOINTS):
        return None
    try:
        validate_endpoints(endpoints)
    except ValueError:
        return None
    return {key: float(endpoints[key]) for key in LEAD_ENDPOINTS}


def validated_properties(compound: Compound) -> dict[str, float] | None:
    values = effective_property_values(compound)
    if any(
        type(values.get(key)) not in {int, float} or not math.isfinite(values[key])
        for key in METRIC_KEYS
    ):
        return None
    result = {key: float(values[key]) for key in METRIC_KEYS}
    if result["molecular_weight"] <= 0 or result["tpsa"] < 0:
        return None
    if any(
        not 0 <= result[key] <= 256 or not result[key].is_integer()
        for key in ("hydrogen_bond_donors", "hydrogen_bond_acceptors")
    ):
        return None
    return result


def admet_score(endpoints: dict[str, float]) -> float:
    protection = [1 - endpoints[key] for key in RISK_ENDPOINTS]
    # A strong single liability cannot disappear in an average, but a model
    # probability is not a validated experimental exclusion threshold.
    safety = 0.5 * sum(protection) / len(protection) + 0.5 * min(protection)
    absorption = sum(endpoints[key] for key in ABSORPTION_ENDPOINTS) / 2
    metabolism = sum(1 - endpoints[key] for key in CYP_ENDPOINTS) / len(CYP_ENDPOINTS)
    return 100 * (0.6 * safety + 0.2 * absorption + 0.2 * metabolism)


@dataclass(frozen=True, slots=True)
class ChemicalFeatures:
    graph: str
    isomer: str
    fingerprint: ExplicitBitVect
    scaffold: str | None
    druglikeness: float
    warnings: tuple[str, ...]


def chemical_features(smiles: str) -> ChemicalFeatures:
    from rdkit import Chem
    from rdkit.Chem import QED, rdFingerprintGenerator
    from rdkit.Chem.Scaffolds import MurckoScaffold

    from .analysis_chemistry import canonical_smiles

    canonical = canonical_smiles(smiles)
    molecule = Chem.MolFromSmiles(canonical)
    flat = Chem.Mol(molecule)
    Chem.RemoveStereochemistry(flat)
    # isomericSmiles=True on the stereo-cleared copy retains isotope/charge/salts.
    graph = Chem.MolToSmiles(flat, isomericSmiles=True)
    core = MurckoScaffold.GetScaffoldForMol(flat)
    scaffold = (
        Chem.MolToSmiles(core, isomericSmiles=True) if core.GetNumAtoms() else None
    )
    fingerprint = rdFingerprintGenerator.GetMorganGenerator(
        radius=2, fpSize=2048, includeChirality=True
    ).GetFingerprint(molecule)
    qed_properties = QED.properties(molecule)
    druglikeness = 100 * QED.qed(molecule, qedProperties=qed_properties)
    warnings = []
    if qed_properties.ALERTS:
        warnings.append(
            f"RDKit QED 匹配 {int(qed_properties.ALERTS)} 项结构警报；不是实测毒性结论。"
        )
    if len(Chem.GetMolFrags(molecule)) > 1:
        warnings.append("结构含多个片段，保留完整盐型/组分；模型适用域需要独立核对。")
    if any(
        label == "?"
        for _, label in Chem.FindMolChiralCenters(molecule, includeUnassigned=True)
    ):
        warnings.append(
            "存在未指定构型的潜在手性中心；不得将候选标记解释为绝对构型证明。"
        )
    return ChemicalFeatures(
        graph, canonical, fingerprint, scaffold, druglikeness, tuple(warnings)
    )


def similarity(left: ChemicalFeatures, right: ChemicalFeatures) -> float:
    from rdkit import DataStructs

    return float(DataStructs.TanimotoSimilarity(left.fingerprint, right.fingerprint))


def novelty(features: ChemicalFeatures, nearest: float, same_scaffold: bool) -> float:
    fingerprint_novelty = 1 - nearest
    if features.scaffold is None:
        return 100 * fingerprint_novelty  # acyclic molecules are not one shared core
    return 100 * (0.7 * fingerprint_novelty + 0.3 * int(not same_scaffold))


def _soft_band(value: float, low: float, high: float, decay: float) -> float:
    distance = max(low - value, value - high, 0.0)
    return 100 * max(0.0, 1 - distance / decay)


def physchem_score(
    values: dict[str, float], features: ChemicalFeatures
) -> tuple[float, list[str]]:
    """Transparent soft small-molecule preferences, never an oral RO5 veto."""
    desirability = (
        0.20 * _soft_band(values["molecular_weight"], 200, 550, 650)
        + 0.25 * _soft_band(values["logP"], 0, 4, 6)
        + 0.20 * _soft_band(values["tpsa"], 20, 140, 180)
        + 0.10 * _soft_band(values["hydrogen_bond_donors"], 0, 5, 10)
        + 0.10 * _soft_band(values["hydrogen_bond_acceptors"], 0, 10, 20)
        + 0.15 * _soft_band(values["Solubility_AqSolDB"], -3, 5, 7)
    )
    warnings = list(features.warnings)
    if values["molecular_weight"] > 800 or values["tpsa"] > 200 or values["logP"] > 6:
        warnings.append(
            "大分子/高极性/高脂溶性区域可能超出 ADMET/QED 适用域；未应用口服 RO5 硬过滤。"
        )
    return 0.8 * desirability + 0.2 * features.druglikeness, warnings
