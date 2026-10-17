"""Strict source-led export validation and qualified record selection."""

from __future__ import annotations

from .formal_structure import binding_pairs, confirmed_binding, image_exists
from .ocsr.recognition_policy import record_errors
from .pipeline_rules import _label_key


def qualified_records(
    bindings: list[dict],
    records: list[dict],
    root: str = "",
    *,
    source_findings: dict[str, list[str]] | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """Reject malformed ownership; retain scientific failures and process only clean pairs."""
    if binding_pairs(bindings) != binding_pairs(records, "cpd_id"):
        raise ValueError(
            "Recognition does not exactly cover the ordered printed-ID catalog"
        )
    if source_findings is None and any(
        binding.get("additional_sources") for binding in bindings
    ):
        raise ValueError("Reprint findings are required before qualified source export")
    selected_bindings, selected_records, errors = [], [], []
    for binding, record in zip(bindings, records):
        reasons = record_errors(record, binding)
        reasons.extend(
            (source_findings or {}).get(
                _label_key(binding.get("cpd") or binding.get("compound_id")), []
            )
        )
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
