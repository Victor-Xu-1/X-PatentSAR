"""One source-bound snapshot of current effective project results, not a new parser."""

from __future__ import annotations

import hashlib
import time

from ..errors import WebError
from ..history_storage import ensure_project_visible
from ..prediction_identity import source_stereo_blocked
from ..service import WorkspaceService
from ..storage import encode
from .input_records import InputBudget, check_deadline, metric_key, molecule_record
from .models import Metric, Molecule, Observation
from .observation_contexts import ObservationContexts, conditions_sha256
from .research_inputs import project_evidence


def project_revision(
    service: WorkspaceService,
    identifier: str,
    *,
    condition_sha: str | None = None,
    include_research: bool = False,
) -> str:
    used = 0
    result = hashlib.sha256()
    with service.store.connect() as connection:
        connection.execute("BEGIN")
        ensure_project_visible(connection, identifier)
        if connection.execute(
            "SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",
            (identifier,),
        ).fetchone():
            raise WebError(
                409,
                "sar_source_busy",
                "Wait for extraction to stop before snapshotting its results.",
            )
        for statement in (
            "SELECT id,sha256,expected_sha256,run_root,snapshot FROM projects WHERE id=?",
            "SELECT id,ordinal,payload,image_path,geometry_space FROM compounds WHERE project_id=? ORDER BY id",
            "SELECT compound_id,revision,fields,basis_fingerprint FROM corrections WHERE project_id=? ORDER BY compound_id",
            "SELECT compound_id,decision,revision FROM reviews WHERE project_id=? ORDER BY compound_id",
            "SELECT compound_id,source_fingerprint,crop_sha256,observation FROM compound_recognitions WHERE project_id=? ORDER BY compound_id",
        ):
            for row in connection.execute(statement, (identifier,)):
                data = encode(list(row)).encode()
                used += len(data)
                if used > 64 * 1024 * 1024:
                    raise WebError(
                        413,
                        "sar_dataset_limit",
                        "Project source snapshot exceeds its bound.",
                    )
                result.update(data)
                result.update(b"\n")
        if include_research:
            for table in ("admet_predictions", "molecular_descriptors"):
                for row in connection.execute(
                    f"SELECT compound_id,source_fingerprint,smiles_sha256,epoch,payload,job_id FROM {table} WHERE project_id=? ORDER BY compound_id,source_fingerprint,smiles_sha256,epoch",
                    (identifier,),
                ):
                    data = encode(list(row)).encode()
                    used += len(data)
                    if used > 64 * 1024 * 1024:
                        raise WebError(
                            413,
                            "sar_dataset_limit",
                            "Research snapshot exceeds its complete-input bound.",
                        )
                    result.update(data)
                    result.update(b"\n")
    result.update(
        (condition_sha or conditions_sha256(service.store.project(identifier))).encode()
    )
    return ("research2:" if include_research else "") + result.hexdigest()


def project_inputs(
    service: WorkspaceService, identifier: str
) -> tuple[list[Molecule], list[Metric], str, str, str | None]:
    # This is an explicit user snapshot action. Current read-model refresh is
    # the existing source authority; SAR never edits its chemistry or acceptance.
    source = service.project(identifier)
    rich_contexts = ObservationContexts(service.store.project(identifier))
    before = project_revision(
        service,
        identifier,
        condition_sha=rich_contexts.source_sha256,
        include_research=True,
    )
    compounds = service.result_queries.research_compounds(identifier)
    if not compounds:
        raise WebError(
            422, "sar_source_empty", "This project has no extracted records to analyse."
        )
    started = time.monotonic()
    output = []
    metrics: dict[str, Metric] = {}
    total = 0
    budget = InputBudget()
    for ordinal, item in enumerate(compounds, 1):
        check_deadline(started)
        observations = []
        for activity in item.activities:
            key = metric_key(
                activity.name, activity.unit, activity.target, activity.assay
            )
            metrics.setdefault(
                key,
                Metric(
                    id=key,
                    name=activity.name,
                    unit=activity.unit,
                    target=activity.target,
                    assay=activity.assay,
                ),
            )
            for recorded_context in rich_contexts.contexts(item.id, activity):
                observations.append(
                    Observation(
                        metric_id=key,
                        value="" if activity.value is None else str(activity.value),
                        unit=activity.unit,
                        context=recorded_context,
                        source_page=activity.page,
                        source_kind="manual"
                        if item.correction and item.correction.has_changes
                        else "patent",
                    )
                )
                total += 1
        if total > 100000 or len(metrics) > 1000:
            raise WebError(
                413,
                "sar_observation_limit",
                "Project observations exceed their complete snapshot limit.",
            )
        issues = []
        if (
            item.confidence.level != "high"
            or item.id.startswith("source-structure:")
            or {
                "structure_number_unconfirmed",
                "ambiguous_binding",
                "historical_identity",
                "structure_unmatched",
            }.intersection(item.flags)
        ):
            issues.append("unverified_source_identifier")
        if item.recognition.status != "valid" or source_stereo_blocked(item):
            issues.append("unverified_source_structure")
        if item.correction and item.correction.stale:
            issues.append("stale_correction")
        if item.review and item.review.decision == "rejected":
            issues.append("review_rejected")
        record, _ = molecule_record(
            ordinal,
            item.identifier_label or item.display_id,
            item.smiles,
            observations,
            item.structure_molfile,
            issues,
            source_compound_id=item.id,
            source_page=item.source.page,
            **project_evidence(item),
        )
        budget.add(record)
        output.append(record)
    after = project_revision(service, identifier, include_research=True)
    if before != after:
        raise WebError(
            409,
            "sar_source_changed",
            "Source results changed during snapshot; no partial dataset was published.",
        )
    return output, list(metrics.values()), before, source.title, source.pdf.sha256
