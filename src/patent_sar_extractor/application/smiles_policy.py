"""Application names delegate to the single core source-recognition policy."""

from patent_sar_extractor.core.ocsr.recognition_policy import (
    recognition_acceptance_errors as _smiles_acceptance_errors,
)


def _smiles_results_can_be_reused(
    smiles_payload: dict, bindings_payload: dict
) -> tuple[bool, list[str]]:
    """A completed SMILES file is reusable only if it passes current strict gates."""
    errors = _smiles_acceptance_errors(smiles_payload, bindings_payload)
    return not errors, errors
