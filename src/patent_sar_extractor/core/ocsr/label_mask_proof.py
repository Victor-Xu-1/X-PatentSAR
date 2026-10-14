"""Pure replay of prepared-image proof shared by core, export and Web consumers."""

from patent_sar_extractor.contracts import OCSR_PREPARATION_VERSION
from patent_sar_extractor.core.printed_identifiers import identifier_key

from .label_mask import _box, _caption_box


def legacy_mask_record(record: dict) -> bool:
    """Old observations stay readable, not eligible for current chemistry."""
    return (
        record.get("ocsr_label_masked") is True
        and "OCSR_preparation_version" not in record
        and "ocsr_label_mask_proof" not in record
    )


def validate_mask_proof(
    record: dict, binding: dict | None = None, source_record: dict | None = None
) -> None:
    """Recheck serialized source identity and projection, not a saved mask flag."""
    masked = any(key.startswith("ocsr_label_mask") for key in record)
    if not masked:
        return
    proof = record.get("ocsr_label_mask_proof")
    if (
        record.get("ocsr_label_masked") is not True
        or not isinstance(proof, dict)
        or type(proof.get("version")) is not int
        or proof["version"] != OCSR_PREPARATION_VERSION
        or type(record.get("OCSR_preparation_version")) is not int
        or record["OCSR_preparation_version"] != OCSR_PREPARATION_VERSION
        or record.get("ocsr_original_input") != record.get("ocsr_label_mask_source")
        or not isinstance(record.get("ocsr_original_input"), str)
        or not record["ocsr_original_input"]
        or not isinstance(record.get("ocsr_structure_image"), str)
        or not record["ocsr_structure_image"]
        or record.get("ocsr_structure_image") == record["ocsr_original_input"]
        or proof.get("source_image_sha256") != record.get("image_hash")
    ):
        raise ValueError(
            "Unproved or legacy OCSR caption cleanup cannot qualify source chemistry"
        )
    frame = proof.get("source_geometry")
    label = identifier_key(record.get("cpd_id"), wrapped=True)
    size = (record.get("stereochemistry") or {}).get("image_size")
    item = {
        "page_no": record.get("page_no"),
        "structure_id": record.get("ocsr_source_structure_id")
        or record.get("structure_id"),
        "exact_caption_evidence": proof.get("caption"),
    }
    if (
        not label
        or not isinstance(frame, dict)
        or not isinstance(size, list)
        or len(size) != 2
    ):
        raise ValueError("OCSR caption cleanup lacks exact original identity")
    if binding is not None and (
        identifier_key(binding.get("cpd") or binding.get("compound_id"), wrapped=True)
        != label
        or binding.get("exact_caption_evidence") != proof.get("caption")
        or binding.get("page_no") != record.get("page_no")
        or (binding.get("source_structure_id") or binding.get("structure_id"))
        != item["structure_id"]
        or "_ocsr_source_geometry" in binding
        and binding["_ocsr_source_geometry"] != frame
    ):
        raise ValueError("OCSR caption cleanup conflicts with the original binding")
    if binding is not None and "_ocsr_source_geometry" not in binding:
        source = source_record or binding
        bounds = _box(
            source.get("bbox_pdf")
            or [
                source.get(key)
                for key in ("struct_x0", "struct_y0", "struct_x1", "struct_y1")
            ]
        )
        if (
            bounds is None
            or bounds != _box(frame.get("bbox"))
            or source.get("structure_id") != item["structure_id"]
            or type(source.get("page_no")) is not int
            or source.get("page_no") != record.get("page_no")
        ):
            raise ValueError(
                "OCSR caption crop is not the original owned structure geometry"
            )
    expected = _caption_box(item, label, frame, size, record.get("image_hash"))
    box = record.get("ocsr_label_mask_bbox")
    if (
        expected is None
        or not isinstance(box, list)
        or any(type(n) is not int for n in box)
        or box != expected
        or record.get("ocsr_label_mask_label") != label
    ):
        raise ValueError("OCSR caption cleanup disagrees with original source geometry")
