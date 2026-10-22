"""Safe read adapter for the same complete source replay, never compound admission."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from patent_sar_extractor.core.ocsr.candidate_observations import (
    build_candidate_plan,
    validate_candidate_observations,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.smiles_artifact import (
    smiles_artifact_is_current,
    smiles_candidate_records,
)

from .errors import WebError


@dataclass(frozen=True)
class SourceObservations:
    records: dict[str, dict]
    errors: list[str]


class _SourceDigests:
    """Call-local stat-bound memoization behind the existing no-follow reader."""

    def __init__(self, files):
        self.files = files
        self.values = {}

    def __call__(self, path):
        try:
            stream = self.files.open(path, max_bytes=16 * 1024 * 1024)
        except WebError as error:
            if error.code == "asset_unavailable":
                return None
            raise
        with stream:
            before = os.fstat(stream.fileno())
            signature = (
                str(self.files.relative(path)),
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            value = self.values.get(signature)
            if value is None:
                value = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
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
                raise ValueError("Original source changed during observation replay")
            self.values[signature] = value
            return value


def read_source_observations(files, payloads, original_sha, *, open_original=None):
    """Revalidate original metadata/producer/all outputs using one shared policy."""
    payload = payloads.get("smiles")
    if not smiles_artifact_is_current(payload, require_all_candidates=True):
        return SourceObservations(
            {}, ["Complete detected-image observations are missing or incompatible."]
        )
    if not original_sha:
        return SourceObservations({}, ["Original source identity is unverified."])
    try:
        digest = _SourceDigests(files)
        plan = build_candidate_plan(
            payloads.get("structures"),
            files.json("structures/metadata.json.manifest.json", optional=False),
            recognition_inputs(payloads.get("bindings") or {}),
            original_pdf_sha256=original_sha,
            metadata_dir=files.root / "structures",
            binding_dir=files.root / "structure_bindings",
            read_digest=digest,
        )
        validate_candidate_observations(plan, payload, read_digest=digest)
        from patent_sar_extractor.core.binding_original_replay import (
            original_binding_source_errors,
            original_binding_sources,
        )

        if original_binding_sources(
            plan.proven.work_items,
            role_text=plan.proven.role_text,
            plot_references=plan.proven.plot_references,
        ):
            if open_original is None:
                raise ValueError("Original PDF is required for binding/source replay")
            with open_original() as document:
                if original_binding_source_errors(
                    document,
                    plan.proven.work_items,
                    role_text=plan.proven.role_text,
                    plot_references=plan.proven.plot_references,
                ):
                    raise ValueError("Original binding/source replay failed")
    except (OSError, ValueError, TypeError, KeyError, OverflowError, WebError):
        return SourceObservations(
            {},
            [
                "Complete detected-image source replay failed; original observations remain unaccepted."
            ],
        )
    return SourceObservations(
        {row["structure_id"]: row for row in smiles_candidate_records(payload)}, []
    )
