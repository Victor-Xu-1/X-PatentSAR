"""One immutable study/input preparation per bounded preview request."""

from dataclasses import dataclass, field

from ..errors import WebError
from .assets import digest
from .models import SARJob
from .preview_models import StudyPreview
from .study_results import StudyResults
from .study_view_models import CurrentRecordView


@dataclass(slots=True)
class PreviewSource:
    job: SARJob
    report: CurrentRecordView
    packet: dict
    sources: dict
    rows: dict
    summaries: dict
    matchers: dict = field(default_factory=dict)


@dataclass(slots=True)
class VerifiedPreview:
    data: StudyPreview
    reference: dict
    candidate: dict
    proof: dict


def load_source(queue, identifier: str) -> PreviewSource:
    job, report, _ = StudyResults(queue).current(identifier, records_only=True)
    record = queue.jobs.record(identifier)
    packet = queue.service.assets.job_files(record["root"], identifier).json(
        "input.json", optional=False
    )
    if digest(packet) != job.input_sha256 or packet.get("schema") not in {2, 3, 4}:
        raise WebError(
            409,
            "sar_input_changed",
            "Preview source differs from immutable study input.",
        )
    return PreviewSource(
        job,
        report,
        packet,
        {row["id"]: row for row in packet["molecules"]},
        {row.molecule_id: row for row in report.rows},
        {item.region.id: item for item in report.regions},
    )
