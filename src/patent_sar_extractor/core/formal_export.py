"""Strict source-led export validation and qualified record selection."""

from __future__ import annotations

import re

from .formal_structure import binding_pairs, confirmed_binding, image_exists
from .ocsr.smiles_qc import COMMON_FINAL_PRODUCT_ELEMENTS
from .ocsr.stereo_gate import stereo_record_error


def record_errors(record: dict) -> list[str]:
    if not isinstance(record, dict):
        raise ValueError("Malformed recognition record")  # noqa: TRY004 -- shared schema boundary
    errors = []
    if not record.get("rdkit_valid") or not record.get("canonical_smiles"):
        errors.append("no clean RDKit-valid SMILES")
    if (
        record.get("OCSR_quality_flag", "ok") != "ok"
        or record.get("has_dummy_atom")
        or record.get("has_query_atom")
    ):
        errors.append(
            f"recognition requires review ({record.get('OCSR_quality_flag', '')})"
        )
    elements = set(
        re.findall(r"\[([A-Z][a-z]?)", str(record.get("canonical_smiles") or ""))
    )
    suspicious = elements - COMMON_FINAL_PRODUCT_ELEMENTS
    suspicious.update(
        str(element)
        for element in record.get("suspicious_elements", [])
        if str(element)
    )
    if suspicious:
        errors.append(f"suspicious elements: {sorted(suspicious)}")
    stereo = stereo_record_error(record)
    if stereo:
        errors.append(f"source stereochemistry: {stereo}")
    return errors


def qualified_records(
    bindings: list[dict], records: list[dict], root: str = ""
) -> tuple[list[dict], list[dict], list[str]]:
    """Reject malformed ownership; retain scientific failures and process only clean pairs."""
    if binding_pairs(bindings) != binding_pairs(records, "cpd_id"):
        raise ValueError(
            "Recognition does not exactly cover the ordered printed-ID catalog"
        )
    selected_bindings, selected_records, errors = [], [], []
    for binding, record in zip(bindings, records):
        reasons = record_errors(record)
        if not confirmed_binding(binding):
            reasons.append("original binding is not independently confirmed")
        if not image_exists(binding, root):
            reasons.append("original structure image is unavailable")
        if reasons:
            errors.extend(f"{binding.get('cpd')}: {reason}" for reason in reasons)
        else:
            selected_bindings.append(binding)
            selected_records.append(record)
    return selected_bindings, selected_records, errors
