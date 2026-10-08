"""Bounded API fallback at an unparsed activity-header boundary, never values.

Deterministic source-ID/column validation constructs every candidate locally.
The model selects one supplied role; the same parser rereads original cells and
the existing writer/QA own the result. Failure/abstention keeps the original path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
from dataclasses import replace
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.core.activity_header_roles import (
    candidate_schemas,
    header_identity,
)
from patent_sar_extractor.core.activity_models import TableContext
from patent_sar_extractor.core.page_ocr_cache import _pdf_sha256
from patent_sar_extractor.integrations.llm.config import get_evidence_resolution_config
from patent_sar_extractor.integrations.llm.evidence_resolution import (
    EvidenceCallBudget,
    EvidenceCandidate,
    EvidenceObservation,
    EvidenceRequest,
    resolve_evidence,
)
from patent_sar_extractor.integrations.llm.job_context import context_for_run
from patent_sar_extractor.integrations.llm.private_state import read_private

logger = logging.getLogger(__name__)


def make_header_resolver(
    pdf_path: str, output_dir: str, catalog: tuple[str, ...] | str
):
    try:
        policy = get_evidence_resolution_config()
        if policy.mode == "off" or not policy.data_consent or not catalog:
            return None
        if isinstance(catalog, str):
            descriptor = os.open(catalog, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 32 * 1024 * 1024:
                    raise ValueError("Unbounded source catalog")
                payload = json.loads(stream.read(32 * 1024 * 1024 + 1))
            if not artifact_identity_matches(
                payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION
            ):
                raise ValueError("Foreign source catalog")
            entries = payload.get("final_bindings", [])
            if not isinstance(entries, list) or len(entries) > 25000:
                raise ValueError("Invalid source catalog")
            catalog = tuple(entry["cpd"] for entry in entries)
        if any(not isinstance(label, str) or len(label) > 128 for label in catalog):
            raise ValueError("Invalid source identifier")
        if not catalog:
            return None
        original = _pdf_sha256(pdf_path)
        base = str(Path(output_dir).parent)
        context = context_for_run(base, original, policy=policy)
        budget = EvidenceCallBudget(
            context.job_id, policy.max_calls, ledger=context.ledger
        )
    except (OSError, ValueError, TypeError, KeyError):
        logger.warning(
            "Optional API header resolver is unavailable; original rules remain active"
        )
        return None
    proved_ids = frozenset(catalog)

    def resolve(table: TableContext, matrix: list[list[str]], region: dict, page: int):
        schemas = candidate_schemas(table, matrix, proved_ids)
        if not schemas:
            return None
        # No value/compound/SMILES/structure image is sent; only printed headers.
        reference = hashlib.sha256(
            json.dumps([page, region["xs"], region["ys"]], sort_keys=True).encode()
        ).hexdigest()[:24]
        text_id, region_id = f"header:{reference}", f"region:{reference}"
        headers = json.dumps(
            {
                "headers": list(next(iter(schemas.values())).raw_headers),
                "caption": table.raw_caption[:1200],
            },
            ensure_ascii=False,
        )
        observations = (
            EvidenceObservation(text_id, "text", headers),
            EvidenceObservation(
                region_id,
                "region",
                json.dumps(
                    {
                        "page": page,
                        "bbox": [
                            region["xs"][0],
                            region["ys"][0],
                            region["xs"][-1],
                            region["ys"][1],
                        ],
                    }
                ),
            ),
        )
        by_id = {
            f"header-role:{reference}:{column}": (column, schema)
            for column, schema in schemas.items()
        }
        candidates = tuple(
            EvidenceCandidate(
                key,
                f"Original physical column {column}: {matrix[0][column][:160]}; compound identifier header role",
                (text_id, region_id),
            )
            for key, (column, _) in by_id.items()
        )
        request = EvidenceRequest(
            context.job_id,
            original,
            "table-header",
            observations,
            candidates,
            "on-error",
        )
        try:
            result = resolve_evidence(request, budget, config=context.policy)
            valid = (
                result.status == "resolved"
                and len(result.candidates) == 1
                and set(result.candidates[0].observation_ids) == {text_id, region_id}
                and result.candidates[0].candidate_id in by_id
            )
            selected = by_id[result.candidates[0].candidate_id] if valid else None
            # Revalidate against the entire original matrix before admission.
            current = candidate_schemas(table, matrix, proved_ids)
            valid = bool(selected and current.get(selected[0]) == selected[1])
            proof = {
                "method": "llm_api_header_role",
                "original_sha256": original,
                "page_no": page,
                "status": result.status,
                "reason": result.reason,
                "calls_used": result.calls_used,
                "applied": valid,
                "formal_acceptance_changed": False,
            }
            if valid:
                proof.update(
                    candidate_id=result.candidates[0].candidate_id,
                    observation_ids=list(result.candidates[0].observation_ids),
                    physical_column=selected[0],
                    source_sha256=header_identity(matrix, selected[1], page, region),
                )
            path = Path(base) / "evidence_resolution_review.json"
            receipt = (
                read_private(path, 131072)
                if path.exists()
                else {
                    "schema": {
                        "name": "patentsar.evidence-resolution-review",
                        "version": 1,
                    },
                    "authority": "advisory",
                    "original_sha256": original,
                    "formal_acceptance_changed": False,
                }
            )
            if receipt.get("original_sha256") != original:
                raise ValueError("Foreign evidence receipt")
            events = receipt.get("header_resolutions", [])
            if not isinstance(events, list) or len(events) >= 8:
                return None
            receipt["header_resolutions"] = [*events, proof]
            if len(json.dumps(receipt)) > 131072:
                return None
            write_json_atomic(path, receipt)
            return replace(selected[1], header_resolution=proof) if valid else None
        except (OSError, TypeError, ValueError, KeyError):
            logger.warning(
                "Optional API header candidate was not admitted; original evidence preserved"
            )
            return None

    return resolve
