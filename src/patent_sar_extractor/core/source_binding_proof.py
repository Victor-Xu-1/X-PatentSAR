"""Current original-source admission, distinct from historical rule annotations."""

from .pipeline_rules import annotate_binding_accuracy

_ORIGINAL_RULES = frozenset(
    {
        "numbered_structure_table_cell",
        "original_caption_cell",
        "original_heading_standalone",
    }
)


def annotate_source_binding(binding: dict) -> dict:
    """Legacy proposals cannot acquire current source authority through flags."""
    if binding.get("binding_rule") in _ORIGINAL_RULES:
        # The shared validator replays the complete specific original proof;
        # the rule name alone is never sufficient.
        return annotate_binding_accuracy(binding)
    return {
        **binding,
        "accuracy_status": "review_required",
        "evidence_tier": "weak",
        "fail_closed": True,
        "evidence_reasons": [
            "Current source ownership requires original cell, caption or heading proof."
        ],
    }
