"""smiles policy: single application-layer policy authority."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from patent_sar_extractor.core.ocsr.smiles_qc import (
    COMMON_FINAL_PRODUCT_ELEMENTS as _AUTO_ACCEPTED_SMILES_ELEMENTS,
)
from patent_sar_extractor.core.ocsr.stereo_gate import stereo_record_error

from .activity_policy import (
    _normalize_cpd_label,
)

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()


def _smiles_acceptance_errors(
    smiles_results: list[dict], bindings_payload: dict
) -> list[str]:
    bindings = (
        bindings_payload.get("final_bindings", [])
        if isinstance(bindings_payload, dict)
        else []
    )
    bound_cpds = [_normalize_cpd_label(row.get("cpd", "")) for row in bindings]
    smile_cpds = [
        _normalize_cpd_label(row.get("cpd_id", ""))
        for row in smiles_results
        if isinstance(row, dict)
    ]
    errors = []
    if smile_cpds != bound_cpds:
        errors.append(
            "SMILES records do not map one-to-one to confirmed bindings in order."
        )
    expected_pairs = [
        (_normalize_cpd_label(row.get("cpd", "")), str(row.get("structure_id") or ""))
        for row in bindings
    ]
    actual_pairs = [
        (
            _normalize_cpd_label(row.get("cpd_id", "")),
            str(row.get("structure_id") or ""),
        )
        for row in smiles_results
        if isinstance(row, dict)
    ]
    if actual_pairs != expected_pairs:
        errors.append(
            "SMILES records are not tied to the exact confirmed structure images in order."
        )
    for row in smiles_results:
        if not isinstance(row, dict):
            errors.append("A SMILES output record is malformed.")
            continue
        cpd = _normalize_cpd_label(row.get("cpd_id", "")) or "unknown compound"
        stereo_error = stereo_record_error(row)
        if stereo_error:
            errors.append(f"{cpd}: source stereochemistry requires review: {stereo_error}")
        suspicious = {
            element
            for element in re.findall(
                r"\[([A-Z][a-z]?)",
                str(row.get("canonical_smiles") or row.get("raw_smiles") or ""),
            )
            if element not in _AUTO_ACCEPTED_SMILES_ELEMENTS
        }
        suspicious.update(
            str(element)
            for element in (row.get("suspicious_elements") or [])
            if str(element)
        )
        if not row.get("rdkit_valid") or not row.get("canonical_smiles"):
            errors.append(f"{cpd}: no clean RDKit-valid SMILES was produced.")
        elif row.get("OCSR_quality_flag", "ok") != "ok" or suspicious:
            errors.append(
                f"{cpd}: OCSR result requires review (quality={row.get('OCSR_quality_flag')}, elements={sorted(suspicious)})."
            )
    return errors


def _smiles_results_can_be_reused(
    smiles_results: list[dict], bindings_payload: dict
) -> tuple[bool, list[str]]:
    """A completed SMILES file is reusable only if it passes current strict gates."""
    errors = _smiles_acceptance_errors(smiles_results, bindings_payload)
    return not errors, errors
