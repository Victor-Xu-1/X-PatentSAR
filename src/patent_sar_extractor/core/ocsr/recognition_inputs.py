"""A single OCSR batch: formal associations followed by all other proved IDs."""

from __future__ import annotations

from typing import Any

from patent_sar_extractor.core.catalog_reader import (
    MAX_CATALOG_RECORDS,
    read_catalog_entries,
)
from patent_sar_extractor.core.pipeline_rules import _label_key


def recognition_inputs(payload: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    formal = payload.get("final_bindings", [])
    if (
        not isinstance(formal, list)
        or len(formal) > MAX_CATALOG_RECORDS
        or any(not isinstance(row, dict) for row in formal)
    ):
        raise ValueError("Formal recognition inputs must be an ordered binding list.")
    catalog, _ = read_catalog_entries(payload)
    if catalog is None:
        return formal, []
    by_label = {
        _label_key(str(row.get("cpd") or row.get("compound_id") or "")): row
        for row in catalog
    }
    used_labels, used_images = set(), set()
    for row in formal:
        label = _label_key(str(row.get("cpd") or row.get("compound_id") or ""))
        image = str(row.get("structure_id") or "")
        if not label or not image or label in used_labels or image in used_images:
            raise ValueError("Formal recognition ownership is ambiguous.")
        owner = by_label.get(label)
        if owner is not None and owner.get("structure_id") != image:
            raise ValueError(
                "Formal association conflicts with the printed-ID catalog."
            )
        used_labels.add(label)
        used_images.add(image)
    supplemental = []
    for row in catalog:
        label = _label_key(str(row.get("cpd") or row.get("compound_id") or ""))
        if label in used_labels:
            continue
        if row.get("structure_id") in used_images:
            raise ValueError("A catalog image competes with another formal owner.")
        supplemental.append(row)
    if len(formal) + len(supplemental) > MAX_CATALOG_RECORDS:
        raise ValueError("Recognition source collection exceeds its bound.")
    return formal, supplemental


def ordered_source_results(bindings: list[dict], results: list[dict]) -> bool:
    """Failures are observations too; never omit or misassign a source result."""

    def pairs(rows: list[dict], field: str) -> list[tuple[str, str]]:
        return [
            (_label_key(str(row.get(field) or "")), str(row.get("structure_id") or ""))
            for row in rows
            if isinstance(row, dict)
        ]

    return len(results) == len(bindings) and pairs(bindings, "cpd") == pairs(
        results, "cpd_id"
    )
