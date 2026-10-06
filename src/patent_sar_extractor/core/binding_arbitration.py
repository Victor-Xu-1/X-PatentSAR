"""Conflict arbitration and fail-closed final selection."""

from __future__ import annotations

import logging
from typing import (
    Any,
)

from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy

from .binding_candidates import (
    _active_ordered_bindings,
)
from .binding_labels import (
    _binding_label_key,
)
from .binding_observations import (
    _annotate_bindings_with_visible_labels,
    _annotate_isotope_label_evidence,
)

logger = logging.getLogger(__name__)


def _drop_fail_closed_bindings(
    final_bindings: list[dict],
    active_cpds: list[str],
    keep_review_bindings: bool = False,
) -> list[dict]:
    """Hard gate: review-required/conflicting bindings must not enter OCSR."""
    if not final_bindings:
        return final_bindings
    kept: list[dict] = []
    dropped: list[str] = []
    for binding in final_bindings:
        key = _binding_label_key(binding)
        if bool(binding.get("fail_closed")) or str(
            binding.get("accuracy_status") or ""
        ) not in {"", "confirmed"}:
            if keep_review_bindings:
                row = dict(binding)
                row["partial_review_candidate"] = True
                row.setdefault(
                    "review_reason",
                    "Retained for bootstrap partial export; strict acceptance still fails.",
                )
                kept.append(row)
                continue
            dropped.append(key or str(binding.get("cpd") or ""))
            continue
        kept.append(binding)
    if dropped:
        logger.info(
            "   🛑 fail-closed最终闸门: 移除 %d 个不可靠绑定 (%s)",
            len(dropped),
            ", ".join(dropped[:20]),
        )
    return _active_ordered_bindings(kept, active_cpds)


def finalize_binding_candidates(
    final_bindings: list[dict[str, Any]],
    active_cpds: list[str],
    profile: dict[str, Any],
    visible_label_cache: dict[str, dict[str, Any]],
    cached_line_map: dict[int, list[tuple[float, str]]],
) -> list[dict[str, Any]]:
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _annotate_isotope_label_evidence(final_bindings, cached_line_map)
    final_bindings = [annotate_binding_accuracy(binding) for binding in final_bindings]
    keep_review_bindings = bool(profile.get("allow_review_bindings"))
    final_bindings = _drop_fail_closed_bindings(
        final_bindings,
        active_cpds,
        keep_review_bindings=keep_review_bindings,
    )
    final_bindings = [annotate_binding_accuracy(binding) for binding in final_bindings]
    return final_bindings
