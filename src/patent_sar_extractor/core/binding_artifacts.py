"""One binding artifact writer for all supported source layouts."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity,
)

from .activity_identity import normalize_compound
from .binding_catalog import compound_catalog
from .formal_structure import FORMAL_SCOPE, SOURCE_EXECUTION_MODE
from .pipeline_rules import _label_key, summarise_binding_accuracy

_CSV_FIELDS = (
    "cpd",
    "example_id",
    "example_num",
    "compound_id",
    "compound_num",
    "cpd_num",
    "prefix",
    "structure_id",
    "page_no",
    "structure_index",
    "struct_x0",
    "struct_y0",
    "struct_x1",
    "struct_y1",
    "image_path",
    "candidates",
    "binding_rule",
    "visible_label",
    "visual_label_source",
    "visible_label_crop_source",
    "visible_label_multi_candidate",
    "product_context_nearby",
    "product_context_distance",
    "struct_width",
    "struct_height",
    "struct_area",
    "struct_aspect",
    "accuracy_status",
    "evidence_tier",
    "evidence_reasons",
    "fail_closed",
    "visible_labels",
    "source_structure_id",
    "merged_fragment_sources",
    "expanded_from_fragment",
    "isotope_label_evidence",
    "isotope_label_ocr_lines",
)


def write_binding_result(
    directory: Path,
    *,
    patent_id: str,
    bindings: list[dict[str, Any]],
    detected_style: str,
    include_intermediates: bool,
    total_structures: int,
    total_compound_blocks: int,
    table_pages: Sequence[int],
    table_covered_count: int,
    no_binding: Sequence[str],
    unbound_pages: Sequence[Any],
    catalog_bindings: Sequence[dict[str, Any]] = (),
    catalog_sources: Sequence[dict[str, Any]] = (),
    source_issues: Sequence[dict[str, Any] | str] = (),
) -> dict[str, Any]:
    issues = list(source_issues)

    def lossless_sources(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        accepted = []
        for binding in rows:
            label = binding.get("cpd")
            if not isinstance(label, str):
                raise ValueError("Malformed original binding identifier")
            printed = normalize_compound(label)
            if not printed or printed != f"Compound {_label_key(label)}":
                issues.append(
                    {
                        "cpd": label,
                        "structure_id": binding.get("structure_id"),
                        "page_no": binding.get("page_no"),
                        "reason": "shared_proof_identifier_is_not_lossless",
                    }
                )
                continue
            accepted.append({**binding, "patent_id": patent_id})
        return accepted

    catalog = compound_catalog(
        lossless_sources([*catalog_bindings, *bindings]),
        lossless_sources(catalog_sources),
    )
    catalog["formal_acceptance_scope"] = FORMAL_SCOPE
    bindings = [dict(binding) for binding in catalog["entries"]]
    directory.mkdir(parents=True, exist_ok=True)
    output_json = directory / "bindings.json"
    output_csv = directory / "bindings.csv"
    payload = {
        **artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION),
        "execution_mode": SOURCE_EXECUTION_MODE,
        "formal_acceptance_scope": FORMAL_SCOPE,
        "patent_id": patent_id,
        "timestamp": datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
        "detected_style": detected_style,
        "include_intermediates": include_intermediates,
        "total_structures": total_structures,
        "total_compound_blocks": total_compound_blocks,
        "final_bindings_count": len(bindings),
        "accuracy_summary": summarise_binding_accuracy(bindings),
        "authoritative_structure_table_pages": list(table_pages),
        "authoritative_structure_table_covered_count": table_covered_count,
        "no_binding": list(no_binding),
        "final_bindings": bindings,
        "compound_catalog": catalog,
        "source_issues": issues,
        "strict_coverage": {
            "expected_cpds": [binding["cpd"] for binding in bindings],
            "expected_structure_ids": [binding["structure_id"] for binding in bindings],
            "catalog_count": len(bindings),
            "unresolved_sources": issues,
        },
    }
    write_json_atomic(output_json, payload)
    with output_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bindings)
    return {
        **payload,
        "patent_id": patent_id,
        "bindings": bindings,
        "total": total_compound_blocks,
        "bound": len(bindings),
        "detected_style": detected_style,
        "structure_fallback": detected_style == "structure_sequence_fallback",
        "unbound_pages": list(unbound_pages),
        "output_files": {"json": str(output_json), "csv": str(output_csv)},
        "compound_catalog": catalog,
    }
