"""Source-owned supporting readings; no new scientific comparison authority."""

from ...core.sar.observation_pair import recorded_difference
from ...core.sar.study_contexts import context_identity
from ..errors import WebError
from .preview_models import PreviewRecordedMeasurement
from .study_models import StudyContext


def recorded_measurements(
    reference: dict,
    candidate: dict,
    contexts: list[StudyContext],
    selected: set[str],
    *,
    differences: bool = False,
) -> list[PreviewRecordedMeasurement]:
    known = {item.id for item in contexts}
    indexed: list[dict[str, list[dict]]] = []
    for molecule in (reference, candidate):
        values: dict[str, list[dict]] = {}
        for observation in molecule["observations"]:
            identity = context_identity(observation)
            if identity not in known:
                raise WebError(
                    409,
                    "sar_preview_measurements",
                    "Source readings differ from the recorded study contexts.",
                )
            if identity not in selected:
                values.setdefault(identity, []).append(observation)
        indexed.append(values)
    return [
        PreviewRecordedMeasurement(
            context_id=context.id,
            reference_values=[obs["value"] for obs in indexed[0].get(context.id, [])],
            candidate_values=[obs["value"] for obs in indexed[1].get(context.id, [])],
            difference=recorded_difference(
                indexed[0].get(context.id, []),
                indexed[1].get(context.id, []),
                context.metric_id,
            )
            if differences
            else None,
        )
        for context in contexts
        if context.id not in selected
        and (context.id in indexed[0] or context.id in indexed[1])
    ]
