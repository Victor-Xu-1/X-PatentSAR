"""Bounded saved-observation QC; digest keys never retain raw source packets."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict

from patent_sar_extractor.contracts import (
    SMILES_SCHEMA,
    SMILES_SCHEMA_VERSION,
    schema_ref,
    schema_ref_matches,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import RecognitionPlan
from patent_sar_extractor.core.ocsr.reprint_consistency import (
    REPRINT_REVIEW_FLAG,
    reprint_findings,
    unavailable_reprints,
)
from patent_sar_extractor.smiles_artifact import (
    build_smiles_artifact,
    smiles_reprint_records,
)

from .errors import WebError
from .models import Recognition
from .recognition import recognition_status
from .recognition_sources import MAX_COMPLETION_BYTES, source_image_digest
from .storage import encode

_observations: OrderedDict[tuple, tuple[Recognition, str | None, str | None]] = (
    OrderedDict()
)
_observation_lock = threading.Lock()


def checked_observation(
    record: object,
    compound_id: str,
    structure_id: str | None,
    *,
    binding: dict | None = None,
) -> Recognition:
    if (
        not isinstance(record, dict)
        or len(encode(record).encode()) > MAX_COMPLETION_BYTES
    ):
        raise WebError(
            422, "invalid_recognition", "Recognition observation exceeds its bound."
        )
    if (
        record.get("cpd_id") != compound_id
        or record.get("structure_id") != structure_id
    ):
        raise WebError(
            422, "recognition_owner", "Recognition belongs to another numbered source."
        )
    result = Recognition.model_validate(
        recognition_status(record, current=True, binding=binding)
    )
    if result.status == "valid" and (
        record.get("OCSR_status") != "success"
        or not re.fullmatch(r"[a-f0-9]{64}", record.get("model_fingerprint") or "")
        or not isinstance(record.get("canonical_smiles"), str)
        or not 1 <= len(record["canonical_smiles"]) <= 10000
    ):
        raise WebError(
            422,
            "invalid_recognition",
            "Accepted observation lacks bounded producer chemistry.",
        )
    additional = binding.get("additional_sources", []) if binding else []
    try:
        repeated = smiles_reprint_records(record)
    except ValueError as exc:
        raise WebError(
            422, "invalid_recognition", "Additional source observations are invalid."
        ) from exc
    if repeated and not additional:
        raise WebError(
            422,
            "recognition_owner",
            "Additional recognition has no proved original source owner.",
        )
    if additional:
        if not schema_ref_matches(
            record.get("source_schema"),
            schema_ref(SMILES_SCHEMA, SMILES_SCHEMA_VERSION),
        ):
            result.status, result.quality_flag = "unavailable", REPRINT_REVIEW_FLAG
        else:
            plan = RecognitionPlan([binding], [], additional)
            findings = reprint_findings(
                plan, build_smiles_artifact([record], reprint_records=repeated)
            )
            if findings:
                result.status = (
                    "unavailable"
                    if unavailable_reprints(
                        plan, build_smiles_artifact([record], reprint_records=repeated)
                    )
                    else "invalid"
                )
                result.quality_flag = REPRINT_REVIEW_FLAG
    return result


def _saved_observation(
    content: str, compound_id: str, structure_id: str | None, context: str
) -> tuple[Recognition, str | None, str | None]:
    if (
        len(content.encode()) > MAX_COMPLETION_BYTES
        or len(context.encode()) > MAX_COMPLETION_BYTES
    ):
        raise WebError(
            422, "invalid_recognition", "Saved recognition exceeds its bound."
        )
    key = (
        hashlib.sha256(content.encode()).hexdigest(),
        hashlib.sha256(context.encode()).hexdigest(),
        compound_id,
        structure_id,
    )
    with _observation_lock:
        cached = _observations.get(key)
        if cached is not None:
            _observations.move_to_end(key)
            return cached
    try:
        record = json.loads(content)
        scope = json.loads(context)
    except (ValueError, TypeError) as exc:
        raise WebError(
            422, "invalid_recognition", "Saved recognition is not a valid observation."
        ) from exc
    if (
        not isinstance(scope, dict)
        or not isinstance(scope.get("root"), str)
        or not isinstance(scope.get("binding"), dict)
    ):
        raise WebError(
            422,
            "recognition_owner",
            "Saved recognition lacks current original ownership.",
        )
    binding = scope["binding"]
    result = checked_observation(record, compound_id, structure_id, binding=binding)
    value = (
        result,
        record["canonical_smiles"] if result.status == "valid" else None,
        source_image_digest({"run_root": scope["root"]}, binding, record),
    )
    with _observation_lock:
        _observations[key] = value
        while len(_observations) > 512:
            _observations.popitem(last=False)
    return value
