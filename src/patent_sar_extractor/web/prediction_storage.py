"""Pinned ADMET projection configured on the shared molecular evidence store."""

from .molecular_observation_store import MolecularObservationStore
from .prediction_identity import smiles_digest
from .prediction_models import PredictionSummary


class PredictionStore(MolecularObservationStore[PredictionSummary]):
    """Six-metric ADMET observations retain their existing schema and authority."""

    summary_type = PredictionSummary


__all__ = ["PredictionStore", "smiles_digest"]
