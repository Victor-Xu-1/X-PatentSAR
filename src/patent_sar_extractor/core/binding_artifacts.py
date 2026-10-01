"""One binding artifact writer for all supported source layouts."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from patent_sar_extractor.artifact_io import write_json_atomic

from .pipeline_rules import summarise_binding_accuracy

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
) -> dict[str, Any]:
    bindings = [{**binding, "patent_id": patent_id} for binding in bindings]
    directory.mkdir(parents=True, exist_ok=True)
    output_json = directory / "bindings.json"
    output_csv = directory / "bindings.csv"
    write_json_atomic(
        output_json,
        {
            "patent_id": patent_id,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
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
        },
    )
    with output_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bindings)
    return {
        "patent_id": patent_id,
        "bindings": bindings,
        "total": total_compound_blocks,
        "bound": len(bindings),
        "detected_style": detected_style,
        "structure_fallback": detected_style == "structure_sequence_fallback",
        "unbound_pages": list(unbound_pages),
        "output_files": {"json": str(output_json), "csv": str(output_csv)},
    }
