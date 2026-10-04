"""Bounded canonical graph keys; exact raw keys are read-only legacy proof."""

from __future__ import annotations

import hashlib
from functools import lru_cache

from .analysis_chemistry import MAX_SMILES, canonical_smiles
from .errors import WebError


def smiles_digest(smiles: str) -> str:
    # Check the raw bound before caching: stripping a huge padded historical
    # string must not retain an unbounded cache key. Never rewrite stored input.
    if not isinstance(smiles, str) or len(smiles) > MAX_SMILES:
        raise WebError(422, "molecule_limit", "Prediction SMILES exceeds its limit.")
    return _canonical_digest(smiles)


@lru_cache(maxsize=2048)
def _canonical_digest(smiles: str) -> str:
    # Cache only bounded strings/digests, not RDKit molecules or model objects.
    return hashlib.sha256(canonical_smiles(smiles).encode()).hexdigest()


def readable_digests(smiles: str) -> tuple[str, str]:
    """Canonical primary; legacy evidence only for this exact validated string.

    An old raw SHA carries no invertible graph proof. Do not search other rows,
    audit history, molecular similarity or partial structures to reassociate it.
    """
    return smiles_digest(smiles), hashlib.sha256(smiles.encode()).hexdigest()
