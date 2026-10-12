"""Source-owned supporting readings; no new scientific comparison authority."""

from ...core.sar.study_contexts import context_identity
from ..errors import WebError
from .preview_models import PreviewRecordedMeasurement
from .study_models import StudyContext


def recorded_measurements(
    reference: dict,
    candidate: dict,
    contexts: list[StudyContext],
    selected: set[str],
) -> list[PreviewRecordedMeasurement]:
    known = {item.id for item in contexts}
    indexed: list[dict[str, list[str]]] = []
    for molecule in (reference, candidate):
        values: dict[str, list[str]] = {}
        for observation in molecule["observations"]:
            identity = context_identity(observation)
            if identity not in known:
                raise WebError(
                    409,
                    "sar_preview_measurements",
                    "Source readings differ from the recorded study contexts.",
                )
            if identity not in selected:
                values.setdefault(identity, []).append(observation["value"])
        indexed.append(values)
    return [
        PreviewRecordedMeasurement(
            context_id=context.id,
            reference_values=indexed[0].get(context.id, []),
            candidate_values=indexed[1].get(context.id, []),
        )
        for context in contexts
        if context.id not in selected
        and (context.id in indexed[0] or context.id in indexed[1])
    ]
