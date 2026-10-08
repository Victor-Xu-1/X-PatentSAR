"""Validate all report, region and row identities before complete publication."""

from __future__ import annotations

from ..errors import WebError
from .assets import digest
from .models import Dataset, Molecule, Pair, SARJob
from .study_models import StudyReport, StudyRequest


def verify_study(safe, job: SARJob, spec: dict, reply: dict, pairs: list[Pair]) -> str:
    packet = safe.json("input.json", optional=False)
    raw = safe.json("report.json", optional=False)
    if digest(packet) != job.input_sha256 or digest(raw) != reply.get("report_sha256"):
        raise WebError(
            502, "sar_result_invalid", "Study input/report identity differs."
        )
    report = StudyReport.model_validate(raw)
    dataset = Dataset.model_validate(packet["dataset"])
    request = StudyRequest.model_validate(packet["request"])
    molecules = [Molecule.model_validate(row) for row in packet["molecules"]]
    ids = {row.id for row in molecules}
    region_refs = {row["id"]: row["molecule_id"] for row in packet["regions"]}
    expected = {
        (region_id, mid)
        for region_id, ref in region_refs.items()
        for mid in ids
        if mid != ref
    }
    actual = {(pair.region_id, pair.molecule_id) for pair in pairs}
    if (
        packet.get("schema") != 2
        or packet.get("job_id") != job.id
        or report.dataset_id != job.dataset_id
        or report.dataset_revision != dataset.revision
        or report.input_sha256 != job.input_sha256
        or report.engine_sha256 != spec["engine_sha256"]
        or report.molecule_count != len(molecules)
        or report.eligible_count != sum(row.eligible for row in molecules)
        or len(report.rows) != len(molecules)
        or {row.molecule_id for row in report.rows} != ids
        or report.strict_pair_count != len(expected)
        or actual != expected
        or len(pairs) != len(expected)
        or {summary.region.id for summary in report.regions} != set(region_refs)
        or len(report.regions) != len(region_refs)
        or report.policies != request.policies
        or len(report.candidates) > request.candidate_count
        or any(row.molecule_id not in ids for row in report.candidates)
        or any(pair.reference_id != region_refs.get(pair.region_id) for pair in pairs)
    ):
        raise WebError(
            502,
            "sar_result_incomplete",
            "Study did not account for every source row and region comparison.",
        )
    by_id = {row.id: row for row in molecules}
    if any(
        row.label != by_id[row.molecule_id].label
        or row.eligible != by_id[row.molecule_id].eligible
        for row in report.rows
    ):
        raise WebError(
            502,
            "sar_result_invalid",
            "Study row identity or eligibility differs from its source.",
        )
    for scaffold in report.scaffolds:
        if (
            not set(scaffold.molecule_ids).issubset(ids)
            or len(set(scaffold.molecule_ids)) != scaffold.molecule_count
        ):
            raise WebError(
                502,
                "sar_result_invalid",
                "Scaffold coverage differs from source membership.",
            )
    for summary in report.regions:
        original = next(
            item for item in packet["regions"] if item["id"] == summary.region.id
        )
        if (
            summary.region.model_dump() != original
            or sum(
                (
                    summary.matched,
                    summary.not_matched,
                    summary.ambiguous,
                    summary.ineligible,
                )
            )
            != len(molecules) - 1
        ):
            raise WebError(
                502,
                "sar_result_invalid",
                "Region summary does not account for its whole comparison pool.",
            )
        for fragment in summary.fragments:
            if (
                not set(fragment.molecule_ids).issubset(ids)
                or len(set(fragment.molecule_ids)) != fragment.molecule_count
            ):
                raise WebError(
                    502,
                    "sar_result_invalid",
                    "Fragment coverage differs from source membership.",
                )
    for pair in pairs:
        if pair.label != by_id[pair.molecule_id].label:
            raise WebError(502, "sar_result_invalid", "Study source label differs.")
    return digest(raw)
