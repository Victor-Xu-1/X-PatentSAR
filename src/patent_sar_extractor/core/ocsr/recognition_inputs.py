"""One bounded source plan for primary compounds and every proved reprint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from patent_sar_extractor.core.catalog_reader import (
    MAX_CATALOG_RECORDS,
    read_catalog_entries,
)
from patent_sar_extractor.core.pipeline_rules import _label_key

_SOURCE_INPUT_FIELDS = (
    "image_path",
    "source_image_path",
    "ocsr_image_path",
    "structure_image",
    "source_structure_id",
    "page_no",
    "bbox_pdf",
    "struct_x0",
    "struct_y0",
    "struct_x1",
    "struct_y1",
    "binding_rule",
    "expanded_from_fragment",
    "exact_caption_evidence",
    "visible_label",
    "visible_label_candidates",
)


@dataclass(frozen=True)
class RecognitionPlan:
    formal: list[dict]
    supplemental: list[dict]
    reprints: list[dict]

    @property
    def work_items(self) -> list[dict]:
        return [*self.formal, *self.supplemental, *self.reprints]


def recognition_inputs(payload: dict[str, Any]) -> RecognitionPlan:
    formal = payload.get("final_bindings", [])
    if (
        not isinstance(formal, list)
        or len(formal) > MAX_CATALOG_RECORDS
        or any(not isinstance(row, dict) for row in formal)
    ):
        raise ValueError("Formal recognition inputs must be an ordered binding list.")
    catalog, _ = read_catalog_entries(payload)
    by_label = {
        _label_key(str(row.get("cpd") or row.get("compound_id") or "")): row
        for row in catalog or []
    }
    used_labels, used_images = set(), set()
    for row in formal:
        label = _label_key(str(row.get("cpd") or row.get("compound_id") or ""))
        image = str(row.get("structure_id") or "")
        if not label or not image or label in used_labels or image in used_images:
            raise ValueError("Formal recognition ownership is ambiguous.")
        owner = by_label.get(label)
        if catalog is not None and owner is None:
            raise ValueError("Formal recognition has no proved printed-ID owner.")
        if owner is not None and owner.get("structure_id") != image:
            raise ValueError(
                "Formal association conflicts with the printed-ID catalog."
            )
        if owner is not None and any(
            row.get(field) != owner.get(field) for field in _SOURCE_INPUT_FIELDS
        ):
            raise ValueError(
                "Formal recognition source differs from the proved original owner."
            )
        used_labels.add(label)
        used_images.add(image)
    supplemental = []
    reprints = []
    for row in catalog or []:
        label = _label_key(str(row.get("cpd") or row.get("compound_id") or ""))
        if label not in used_labels:
            if row.get("structure_id") in used_images:
                raise ValueError("A catalog image competes with another formal owner.")
            supplemental.append(row)
            used_images.add(row["structure_id"])
        for source in row.get("additional_sources", []):
            if source["structure_id"] in used_images:
                raise ValueError("A reprint image competes with another source owner.")
            reprints.append(source)
            used_images.add(source["structure_id"])
    if len(formal) + len(supplemental) + len(reprints) > MAX_CATALOG_RECORDS:
        raise ValueError("Recognition source collection exceeds its bound.")
    return RecognitionPlan(formal, supplemental, reprints)


def ordered_source_results(bindings: list[dict], results: list[dict]) -> bool:
    """Failures are observations too; never omit or misassign a source result."""

    def pairs(rows: list[dict], field: str) -> list[tuple[str, str]]:
        return [
            (
                _label_key(
                    str(
                        row.get(field)
                        or (row.get("compound_id") if field == "cpd" else "")
                        or ""
                    )
                ),
                str(row.get("structure_id") or ""),
            )
            for row in rows
            if isinstance(row, dict)
        ]

    return len(results) == len(bindings) and pairs(bindings, "cpd") == pairs(
        results, "cpd_id"
    )
