"""One read-only multi-candidate projection of the retained strict preview path."""

from ...core.sar.errors import SARInputError
from ..errors import WebError
from .matrix_drawing import matrix_drawings
from .matrix_models import StudyMatrix
from .preview_source import load_source
from .study_preview import verified_preview


def matrix(
    queue, identifier: str, reference_id: str, regions: list[str], molecules: list[str]
):
    if (
        not 1 <= len(molecules) <= 6
        or len(regions) != len(molecules)
        or len(set(molecules)) != len(molecules)
        or any(
            not value or len(value) > 200
            for value in [reference_id, *regions, *molecules]
        )
    ):
        raise WebError(
            422, "sar_preview_selection", "Choose up to six distinct strict members."
        )
    source = load_source(queue, identifier)
    if any(
        region not in source.summaries
        or source.summaries[region].region.molecule_id != reference_id
        for region in regions
    ):
        raise WebError(
            422, "sar_preview_selection", "Every direction must use the same reference."
        )
    selections = [
        verified_preview(queue, source, region, molecule)
        for region, molecule in zip(regions, molecules, strict=True)
    ]
    try:
        reference = matrix_drawings(selections)
    except (SARInputError, ValueError, RuntimeError, OverflowError) as error:
        raise WebError(
            422,
            "sar_structure_unavailable",
            "Matrix structure drawing is unavailable; no chemical placeholder was substituted.",
        ) from error
    result = StudyMatrix(
        reference_drawing=reference, previews=[item.data for item in selections]
    )
    if len(result.model_dump_json().encode("utf-8")) > 8 * 1024 * 1024:
        raise WebError(
            413, "sar_preview_limit", "Complete matrix exceeds the preview byte budget."
        )
    return result
