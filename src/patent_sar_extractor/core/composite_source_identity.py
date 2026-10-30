"""Canonical identities for bounded inventories of independently bounded facts."""

import hashlib
import json

from .source_evidence_identity import SourceEvidenceLimit


def composite_source_digest(source, partitions, *, maximum, component_limit, label):
    """Hash the exact canonical JSON, without expanding a complete inventory.

    Only explicitly listed dictionary/list paths split an inventory into bounded
    components. All other values retain the original per-source byte limit.
    A list element is represented by ``*`` in a partition path.
    """
    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    digest, total = hashlib.sha256(), 0

    def append(part, remaining):
        nonlocal total
        if len(part) > remaining:
            raise SourceEvidenceLimit(
                f"Original {label} component exceeds its byte budget"
            )
        if len(part) > maximum - total:
            raise SourceEvidenceLimit(f"Original {label} exceeds its byte budget")
        encoded = part.encode("utf-8")
        if len(encoded) > remaining:
            raise SourceEvidenceLimit(
                f"Original {label} component exceeds its byte budget"
            )
        if len(encoded) > maximum - total:
            raise SourceEvidenceLimit(f"Original {label} exceeds its byte budget")
        total += len(encoded)
        digest.update(encoded)
        return len(encoded)

    def component(value):
        size = 0
        for part in encoder.iterencode(value):
            size += append(part, component_limit - size)

    def walk(value, path):
        if path not in partitions:
            component(value)
            return
        if isinstance(value, dict):
            append("{", maximum)
            for index, key in enumerate(sorted(value)):
                if index:
                    append(",", maximum)
                append(encoder.encode(key), component_limit)
                append(":", maximum)
                walk(value[key], (*path, key))
            append("}", maximum)
        elif isinstance(value, list):
            append("[", maximum)
            for index, item in enumerate(value):
                if index:
                    append(",", maximum)
                walk(item, (*path, "*"))
            append("]", maximum)
        else:
            component(value)

    walk(source, ())
    return digest.hexdigest()
