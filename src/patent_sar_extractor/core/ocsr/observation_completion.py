"""Complete source observations do not certify scientific acceptance.

The standalone runner remains strict by default. The source-led coordinator can
collect complete findings for its final QA, without bypassing input/coverage
validation or turning infrastructure exceptions into molecular observations.
"""

from __future__ import annotations

from typing import Any

from patent_sar_extractor.core.formal_structure import (
    FORMAL_SCOPE,
    binding_pairs,
    coverage_errors,
    proved_catalog,
)
from patent_sar_extractor.failures import write_failure_marker

from .recognition_inputs import ordered_source_results


def validate_source_observation_mode(
    payload: dict[str, Any],
    bindings: list[dict[str, Any]],
    *,
    diagnostic: bool,
    limit: int | None,
    include_unbound: bool,
) -> None:
    if (
        diagnostic
        or include_unbound
        or (limit is not None and (type(limit) is not int or limit != 0))
    ):
        raise ValueError(
            "Complete source observations cannot be diagnostic, limited or unbound"
        )
    coverage_errors(payload)  # Malformed/foreign producer identity still raises.
    if payload.get("formal_acceptance_scope") != FORMAL_SCOPE:
        raise ValueError(
            "Complete source observations require the current formal source scope"
        )
    if not bindings or binding_pairs(bindings) != binding_pairs(
        proved_catalog(payload)
    ):
        raise ValueError(
            "Complete source observations must cover the exact proved catalog"
        )


def require_complete_source_results(
    bindings: list[dict[str, Any]], results: list[dict[str, Any]]
) -> None:
    if not ordered_source_results(bindings, results):
        raise ValueError(
            "Source observations are incomplete, duplicated or misassigned"
        )


def publish_scientific_findings(
    output_dir: str,
    errors: list[str],
    *,
    continue_on_scientific_errors: bool,
) -> None:
    if not errors:
        return
    write_failure_marker(output_dir, "smiles_output", errors)
    if not continue_on_scientific_errors:
        raise RuntimeError("Strict OCSR output gate failed: " + "; ".join(errors[:12]))
