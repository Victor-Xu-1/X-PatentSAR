"""Saved detected-image scope: bounded identity/accounting, never source admission."""

from patent_sar_extractor.contracts import (
    MAX_RECOGNITION_SOURCES,
    OCSR_RECOGNITION_SCOPE,
)

from ..activity_context_geometry import valid_box
from ..structure_inventory import validate_structure_inventory
from .candidate_inventory import (
    inventory_digest,
    valid_sha,
    valid_source_path,
)
from .recognition_selection import deferred_source_record

SOURCE_ROLES = ("formal", "supplemental", "reprint")
RESULT_FIELDS = ("records", "source_records", "reprint_records", "candidate_records")


def validate_candidate_scope(value, *, group_counts=None):
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "kind",
            "recognition_policy",
            "original_pdf_sha256",
            "metadata_identity",
            "producer_identity",
            "source_inventory",
            "entries",
            "identity",
        }
        or type(value["version"]) is not int
        or value["version"] != 2
        or value["kind"] != "detected_image_inventory"
        or value["recognition_policy"] != OCSR_RECOGNITION_SCOPE
        or any(
            not valid_sha(value[field])
            for field in (
                "original_pdf_sha256",
                "metadata_identity",
                "producer_identity",
                "identity",
            )
        )
        or not isinstance(value["entries"], list)
        or len(value["entries"]) > MAX_RECOGNITION_SOURCES
        or value["identity"]
        != inventory_digest({k: v for k, v in value.items() if k != "identity"})
    ):
        raise ValueError("Malformed complete detected-image observation scope")
    positions, candidates = set(), set()
    for entry in value["entries"]:
        if (
            not isinstance(entry, dict)
            or set(entry)
            != {
                "structure_id",
                "page_no",
                "bbox_pdf",
                "image_path",
                "image_sha256",
                "observation",
            }
            or not valid_box(entry["bbox_pdf"])
            or not valid_source_path(entry["image_path"])
            or entry["image_sha256"] is not None
            and not valid_sha(entry["image_sha256"])
        ):
            raise ValueError("Malformed detected-image original asset")
        reference = entry["observation"]
        if (
            not isinstance(reference, dict)
            or set(reference) != {"role", "index"}
            or not isinstance(reference["role"], str)
            or reference["role"] not in (*SOURCE_ROLES, "candidate")
            or type(reference["index"]) is not int
            or not 0 <= reference["index"] < MAX_RECOGNITION_SOURCES
            or (reference["role"], reference["index"]) in positions
        ):
            raise ValueError(
                "Malformed or duplicated detected-image observation position"
            )
        positions.add((reference["role"], reference["index"]))
        if reference["role"] == "candidate":
            candidates.add(reference["index"])
        if (
            group_counts is not None
            and not reference["index"] < group_counts[reference["role"]]
        ):
            raise ValueError("Detected-image observation position has no result")
    if group_counts is not None and candidates != set(range(group_counts["candidate"])):
        raise ValueError(
            "Unassigned observation results differ from the detected-image inventory"
        )
    validate_structure_inventory(
        {
            "total_structures": len(value["entries"]),
            "structures": value["entries"],
            "source_inventory": value["source_inventory"],
        },
        full_document=True,
    )


def validate_inventory_records(inventory, groups):
    """One pure saved-record boundary; filesystem/source acceptance is separate."""
    counts = {
        role: len(groups[field])
        for role, field in zip((*SOURCE_ROLES, "candidate"), RESULT_FIELDS, strict=True)
    }
    validate_candidate_scope(inventory, group_counts=counts)
    fields = dict(zip((*SOURCE_ROLES, "candidate"), RESULT_FIELDS, strict=True))
    for entry in inventory["entries"]:
        reference = entry["observation"]
        row = groups[fields[reference["role"]]][reference["index"]]
        if reference["role"] == "candidate":
            expected = deferred_source_record(entry, inventory["original_pdf_sha256"])
            if row != expected or any(
                type(row[key]) is not type(value) for key, value in expected.items()
            ):
                raise ValueError(
                    "Unproved source must retain exact no-execution identity, not a molecule"
                )
        else:
            _validate_observed_record(entry, row)
            if row.get("candidate_source_id") is not None:
                raise ValueError(
                    "A proved observation cannot borrow an unassigned source marker"
                )


def _validate_observed_record(entry, row):
    raw, status = row.get("raw_smiles"), row.get("OCSR_status")
    if (
        type(row.get("page_no")) is not int
        or row["page_no"] != entry["page_no"]
        or not isinstance(row.get("ocsr_source_structure_id"), str)
        or row["ocsr_source_structure_id"] != entry["structure_id"]
        or not isinstance(status, str)
        or status
        not in {
            "success",
            "review_required",
            "invalid_smiles",
            "image_missing",
            "preprocessing_failed",
            "engine_timeout",
            "engine_unavailable",
            "all_engines_failed",
            "unavailable",
        }
        or raw is not None
        and not isinstance(raw, str)
        or not valid_source_path(row.get("ocsr_original_input"))
        or status == "success"
        and not raw
        or raw
        and (
            entry["image_sha256"] is None
            or not valid_sha(row.get("model_fingerprint"))
            or not isinstance(row.get("OCSR_engine"), str)
            or not row["OCSR_engine"]
        )
    ):
        raise ValueError(
            "Detected-image result has malformed source/model observation fields"
        )
    if row.get("image_hash") != entry["image_sha256"] and not (
        row.get("image_hash") is None
        and not raw
        and status in {"image_missing", "preprocessing_failed", "review_required"}
    ):
        raise ValueError("Detected-image observation comes from another crop")
