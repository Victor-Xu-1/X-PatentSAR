"""Bounded detected-image provenance, not printed-ID or chemical acceptance."""

import hashlib
import json
import re
from pathlib import Path

from patent_sar_extractor.artifact_nodes import MAX_ARTIFACT_BYTES
from patent_sar_extractor.contracts import (
    MAX_RECOGNITION_SOURCES,
    OCSR_RECOGNITION_SCOPE,
    STEP_MANIFEST_SCHEMA,
    STEP_MANIFEST_SCHEMA_VERSION,
    STRUCTURE_WORKER_VERSION,
    schema_ref,
)

from ..activity_context_geometry import valid_box
from ..structure_inventory import MAX_PAGES, validate_structure_inventory
from .smiles_cache import compute_image_sha256

_SHA = re.compile(r"[a-f0-9]{64}")
PRINTED_ID_FIELDS = (
    "cpd",
    "cpd_id",
    "compound_id",
    "example_id",
    "compound_num",
    "example_num",
    "cpd_num",
    "prefix",
)


def inventory_digest(value):
    """Stream one bounded canonical identity without a second store or encoder."""
    digest, size = hashlib.sha256(), 0
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False)
    for part in encoder.iterencode(value):
        data = part.encode("utf-8")
        size += len(data)
        if size > MAX_ARTIFACT_BYTES:
            raise ValueError("Detected-image observation inventory exceeds its bound")
        digest.update(data)
    return digest.hexdigest()


def valid_sha(value):
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def valid_source_path(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 4096
        and not any(ord(char) < 32 for char in value)
        and Path(value).is_absolute()
    )


def candidate_descriptor(entry, original_sha):
    return {
        **{
            key: entry[key]
            for key in (
                "structure_id",
                "page_no",
                "bbox_pdf",
                "image_path",
                "image_sha256",
            )
        },
        "original_pdf_sha256": original_sha,
    }


def validate_candidate_input(item):
    """Typed observations are not unbound rows promoted to named compounds."""
    if item.get("bind_status") != "candidate":
        return False
    source = item.get("candidate_source")
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "structure_id",
            "page_no",
            "bbox_pdf",
            "image_path",
            "image_sha256",
            "original_pdf_sha256",
        }
        or not valid_sha(source["original_pdf_sha256"])
        or source["image_sha256"] is not None
        and not valid_sha(source["image_sha256"])
        or not isinstance(source["structure_id"], str)
        or not 0 < len(source["structure_id"]) <= 128
        or type(source["page_no"]) is not int
        or not 1 <= source["page_no"] <= MAX_PAGES
        or not valid_box(source["bbox_pdf"])
        or not valid_source_path(source["image_path"])
        or item.get("candidate_source_id") != inventory_digest(source)
        or item.get("cpd") != ""
        or any(item.get(field) not in (None, "") for field in PRINTED_ID_FIELDS)
        or type(item.get("page_no")) is not int
        or any(
            item.get(field) != source[field]
            for field in ("structure_id", "page_no", "bbox_pdf", "image_path")
        )
        or not valid_box(item.get("bbox_pdf"))
        or any(
            item.get(field) not in (None, "", source["image_path"])
            for field in ("source_image_path", "ocsr_image_path", "structure_image")
        )
    ):
        raise ValueError("Malformed unassigned source observation input")
    return True


def asset_digest(path):
    """Unavailable is an observation, never a zero image or a chemical result."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Detected-image source cannot be a symbolic link")
    try:
        before = path.stat()
        if not path.is_file():
            return None
        digest = compute_image_sha256(str(path))
        after = path.stat()
    except OSError:
        return None
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError("Detected-image source changed during observation")
    return digest


def original_candidate_inventory(
    metadata, manifest, original_sha, directory, *, read_digest=asset_digest
):
    """Observe the exact current raw producer input, including zero-crop pages.

    A raw producer manifest establishes its declared PDF/worker provenance. It
    does not certify detector recall, physical ID ownership or molecular truth.
    Old raw observations are not retagged with newer semantic ruleset versions.
    """
    if not valid_sha(original_sha):
        raise ValueError("Detected-image original PDF identity is missing")
    packet = validate_structure_inventory(metadata, full_document=True)
    if len(metadata["structures"]) > MAX_RECOGNITION_SOURCES:
        raise ValueError("Detected-image observation collection exceeds its bound")
    fingerprint = manifest.get("fingerprint") if isinstance(manifest, dict) else None
    params = fingerprint.get("params") if isinstance(fingerprint, dict) else None
    pages = params.get("structure_pages") if isinstance(params, dict) else None
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("schema"), dict)
        or type(manifest["schema"].get("version")) is not int
        or manifest.get("schema")
        != schema_ref(STEP_MANIFEST_SCHEMA, STEP_MANIFEST_SCHEMA_VERSION)
        or not isinstance(fingerprint, dict)
        or fingerprint.get("step") != "structures"
        or fingerprint.get("pdf_sha256") != original_sha
        or not isinstance(params, dict)
        or params.get("structure_worker_contract_version") != STRUCTURE_WORKER_VERSION
        or not isinstance(pages, list)
        or any(type(page) is not int for page in pages)
        or len(pages) != packet["page_count"]
        or set(pages) != set(range(packet["page_count"]))
    ):
        raise ValueError(
            "Detected-image input has no complete original producer provenance"
        )
    entries = []
    for row in metadata["structures"]:
        path, box = row.get("image_path"), row.get("bbox_pdf")
        if (
            not isinstance(path, str)
            or not 0 < len(path) <= 4096
            or any(ord(char) < 32 for char in path)
            or not valid_box(box)
        ):
            raise ValueError(
                "Detected-image source has malformed original geometry or path"
            )
        original = Path(path)
        if not original.is_absolute():
            original = Path(directory) / original
        original = original.absolute()
        entries.append(
            {
                "structure_id": row["structure_id"],
                "page_no": row["page_no"],
                "bbox_pdf": list(box),
                "image_path": str(original),
                "image_sha256": read_digest(original),
            }
        )
    return {
        "version": 2,
        "kind": "detected_image_inventory",
        "recognition_policy": OCSR_RECOGNITION_SCOPE,
        "original_pdf_sha256": original_sha,
        "metadata_identity": inventory_digest(metadata),
        "producer_identity": inventory_digest(manifest),
        "source_inventory": packet,
    }, entries
