"""The existing bounded source-evidence digest, independent of image engines."""

import hashlib
import json


def proof_id(proof: dict) -> str:
    if not isinstance(proof, dict) or not isinstance(proof.get("status"), str):
        raise TypeError("Malformed original header evidence")
    encoded = json.dumps(
        proof,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise ValueError("Original header evidence exceeds its bounded region limit")
    return hashlib.sha256(encoded).hexdigest()
