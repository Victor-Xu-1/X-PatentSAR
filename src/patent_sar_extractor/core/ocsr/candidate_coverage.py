"""One final-QA replay of all detected image observations; no result mutations."""

from pathlib import Path

from patent_sar_extractor.smiles_artifact import smiles_artifact_is_current

from .candidate_inputs import load_source_observation_plan
from .candidate_inventory import inventory_digest
from .candidate_observations import validate_candidate_observations
from .recognition_inputs import recognition_inputs


def saved_candidate_coverage_errors(metadata, payload):
    try:
        if not smiles_artifact_is_current(payload, require_all_candidates=True):
            raise ValueError(
                "Complete detected-image output scope is missing or incompatible"
            )
        if payload["candidate_inventory"]["metadata_identity"] != inventory_digest(
            metadata
        ):
            raise ValueError(
                "Detected-image metadata differs from the captured original input"
            )
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return [f"Complete detected-image observations are unproved: {error}."]
    return []


def candidate_coverage_errors(base, summary, metadata, bindings, payload):
    saved_errors = saved_candidate_coverage_errors(metadata, payload)
    if saved_errors:
        return saved_errors
    try:
        original = summary.get("input_pdf")
        if not isinstance(original, str) or not original:
            raise ValueError("Original PDF is unavailable for input identity replay")
        source = Path(base)
        plan = load_source_observation_plan(
            recognition_inputs(bindings),
            structures_json=source / "structures" / "metadata.json",
            pdf_path=original,
            binding_dir=source / "structure_bindings",
            binding_pdf_sha256=(bindings.get("source_reference_scope") or {}).get(
                "original_pdf_sha256", ""
            ),
        )
        if plan.inventory["metadata_identity"] != inventory_digest(metadata):
            raise ValueError("Detected-image inputs changed during QA")
        validate_candidate_observations(plan, payload)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        return [f"Complete detected-image observations are unproved: {error}."]
    return []
