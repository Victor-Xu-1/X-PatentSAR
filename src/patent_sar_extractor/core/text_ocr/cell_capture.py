"""One complete auxiliary capture path; historical v1 evidence is read-only."""

from .recovery_capture import recover_complete_pair


def refine_text_pair(
    images,
    primaries,
    auxiliary,
    *,
    evidence_sink=None,
    maximum_rows=8,
    allow_chunks=False,
    maximum_row_height=12,
):
    return recover_complete_pair(
        images,
        primaries,
        auxiliary,
        evidence_sink=evidence_sink,
        maximum_rows=maximum_rows,
        allow_chunks=allow_chunks,
        maximum_row_height=maximum_row_height,
    )
