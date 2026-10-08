"""Private bounded study checkpoints; every sealed batch has exact coverage."""

from __future__ import annotations

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.assets import atomic_json, digest
from patent_sar_extractor.web.storage import encode

BATCH_SIZE = 25


def _receipt(identity, start, field, records):
    return {
        **identity,
        "start": start,
        "field": field,
        "records_sha256": digest(records),
        "kind": "native-study-proof-v1",
        "verified": True,
    }


def load(safe, name: str, identity: dict, start: int, field: str):
    value = safe.json(name)
    if value is None:
        path = safe.root / name
        if path.exists() or path.is_symlink():
            raise SARInputError("study_checkpoint_unsafe")
        return None
    checksum = field + "_sha256"
    if (
        not isinstance(value, dict)
        or set(value) != {"input_sha256", "engine_sha256", "start", field, checksum}
        or value["input_sha256"] != identity["input_sha256"]
        or value["engine_sha256"] != identity["engine_sha256"]
        or type(value["start"]) is not int
        or value["start"] != start
        or not isinstance(value[field], list)
        or not 1 <= len(value[field]) <= BATCH_SIZE
        or digest(value[field]) != value[checksum]
    ):
        raise SARInputError("study_checkpoint_identity")
    receipt_name = "native-" + name
    receipt = safe.json(receipt_name)
    if receipt is None:
        if (safe.root / receipt_name).exists() or (
            safe.root / receipt_name
        ).is_symlink():
            raise SARInputError("study_checkpoint_unsafe")
        # A crash between data and receipt publication requires fresh native
        # proof of THIS batch, not a blanket trust of a recomputable checksum.
        return None
    if receipt != _receipt(identity, start, field, value[field]):
        raise SARInputError(
            "study_pair_checkpoint_proof"
            if field == "pairs"
            else "study_descriptor_checkpoint_identity"
        )
    return value[field]


def save(root, name: str, identity: dict, start: int, field: str, records: list[dict]):
    # Bound repeated reference evidence BEFORE assembling a potentially huge
    # complete JSON string. No batch/observation is silently shortened.
    if (
        sum(len(encode(record).encode()) + 1 for record in records)
        > 32 * 1024 * 1024 - 1024
    ):
        raise SARInputError("study_checkpoint_size_limit")
    value = {
        **identity,
        "start": start,
        field: records,
        field + "_sha256": digest(records),
    }
    safe = SafeFiles(root)
    existing = safe.json(name)
    if existing is not None and existing != value:
        raise SARInputError("study_checkpoint_native_proof")
    if existing is None:
        atomic_json(root, name, value)
    receipt_name = "native-" + name
    receipt = _receipt(identity, start, field, records)
    existing_receipt = safe.json(receipt_name)
    if existing_receipt is not None and existing_receipt != receipt:
        raise SARInputError("study_checkpoint_native_proof")
    if existing_receipt is None:
        atomic_json(root, receipt_name, receipt)


def progress(root, identity: dict, processed: int, matched: int):
    atomic_json(
        root, "progress.json", {**identity, "processed": processed, "matched": matched}
    )
