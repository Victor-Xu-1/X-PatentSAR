"""Bounded canonical graph keys; exact raw keys are read-only legacy proof."""

from __future__ import annotations

import hashlib
from functools import lru_cache

from .analysis_chemistry import MAX_SMILES, canonical_smiles
from .correction_chemistry import molfile_representation, validate_structure
from .errors import WebError
from .models import Compound

SOURCE_STEREO_FLAGS = frozenset({"stereo_source_conflict", "stereo_source_ambiguous"})


def source_stereo_blocked(compound: Compound) -> bool:
    recognition = compound.recognition
    if (
        recognition.quality_flag == "manual_correction"
        and compound.correction is not None
        and compound.correction.has_changes
        and not compound.correction.stale
    ):
        # apply_correction grants this state for blocked originals only after a
        # validated graph change, never a coordinate-only/SMILES-alias edit.
        return False
    return (
        recognition.quality_flag in SOURCE_STEREO_FLAGS
        or bool(SOURCE_STEREO_FLAGS.intersection(compound.flags))
        or (
            recognition.stereochemistry is not None
            and recognition.stereochemistry.status in {"conflict", "ambiguous"}
        )
    )


def compound_prediction_eligible(compound: Compound) -> bool:
    return not source_stereo_blocked(compound) and prediction_eligible(
        compound.smiles, compound.structure_molfile
    )


def prediction_eligible(smiles: str | None, molfile: str | None = None) -> bool:
    """Legacy SMILES inputs stay compatible; manual ambiguity never enters inference."""
    if not smiles:
        return False
    if molfile is None:
        return True
    try:
        validate_structure(molfile, smiles)
        return molfile_representation(molfile)[1] is None
    except ValueError as exc:
        raise WebError(
            422,
            "invalid_manual_structure",
            "Manual molecular representation is invalid.",
        ) from exc


def smiles_digest(smiles: str, molfile: str | None = None) -> str:
    # Check the raw bound before caching: stripping a huge padded historical
    # string must not retain an unbounded cache key. Never rewrite stored input.
    if not isinstance(smiles, str) or len(smiles) > MAX_SMILES:
        raise WebError(422, "molecule_limit", "Prediction SMILES exceeds its limit.")
    if not prediction_eligible(smiles, molfile):
        raise WebError(
            422,
            "manual_stereo_unresolved",
            "Explicit manual unknown stereochemistry requires review, not unique-graph inference.",
        )
    return _canonical_digest(smiles)


@lru_cache(maxsize=2048)
def _canonical_digest(smiles: str) -> str:
    # Cache only bounded strings/digests, not RDKit molecules or model objects.
    return hashlib.sha256(canonical_smiles(smiles).encode()).hexdigest()


def readable_digests(smiles: str, molfile: str | None = None) -> tuple[str, str]:
    """Canonical primary; legacy evidence only for this exact validated string.

    An old raw SHA carries no invertible graph proof. Do not search other rows,
    audit history, molecular similarity or partial structures to reassociate it.
    """
    return smiles_digest(smiles, molfile), hashlib.sha256(smiles.encode()).hexdigest()
