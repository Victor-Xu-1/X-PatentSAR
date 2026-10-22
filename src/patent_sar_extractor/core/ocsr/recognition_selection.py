"""Model admission is distinct from complete, immutable drawing accounting."""

from ..cpd_filter import is_intermediate
from .candidate_inventory import (
    candidate_descriptor,
    inventory_digest,
    validate_candidate_input,
)


def require_numbered_model_input(item):
    """Defense in depth; the worker must also replay actual original ownership.

    A bound flag alone is not scientific proof. This rejects explicitly absent
    or non-product identity before any image preparation, cache or model work.
    It never infers an intermediate from an I-prefix or invents a product role.
    """
    if (
        not isinstance(item, dict)
        or validate_candidate_input(item)
        or not isinstance(item.get("cpd"), str)
        or not item["cpd"].strip()
        or is_intermediate(item)
        or item.get("bind_status", "bound") != "bound"
    ):
        raise ValueError("Model recognition requires a proved numbered product source")


def deferred_source_record(entry, original_sha):
    """A literal no-execution record, not a failed prediction or guessed molecule."""
    source = candidate_descriptor(entry, original_sha)
    return {
        "cpd_id": "",
        "structure_id": entry["structure_id"],
        "page_no": entry["page_no"],
        "ocsr_source_structure_id": entry["structure_id"],
        "ocsr_original_input": entry["image_path"],
        "image_hash": entry["image_sha256"],
        "candidate_source_id": inventory_digest(source),
        "recognition_selection": "deferred_unproved_terminal_ownership",
        "OCSR_status": "not_processed",
        "OCSR_quality_flag": "unproved_terminal_ownership",
        "raw_smiles": None,
        "canonical_smiles": None,
        "model_fingerprint": None,
        "OCSR_engine": None,
    }


def deferred_source_records(inventory):
    return [
        deferred_source_record(entry, inventory["original_pdf_sha256"])
        for entry in inventory["entries"]
        if entry["observation"]["role"] == "candidate"
    ]
