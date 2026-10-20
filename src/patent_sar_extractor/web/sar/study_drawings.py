"""One passive renderer shared by individual and bounded batch source readers."""

from ...core.sar.drawing import draw_fragment, draw_molecule_preview
from ..errors import WebError
from .models import Pair
from .study_drawing_models import (
    StudyDrawingBatch,
    StudyDrawingEntry,
    StudyDrawingError,
)
from .study_models import StudyDrawing

MAX_DRAWING_BATCH_BYTES = 6 * 1024 * 1024


def draw_one(queue, identifier, job, report, kind, key, region_id):
    try:
        if kind == "molecule":
            molecule = queue.service.datasets.molecule(job.dataset_id, key)
            if not molecule.eligible or not molecule.molfile:
                raise ValueError("unavailable")
            atoms, hydrogen_anchor = [], None
            if region_id:
                region = next(
                    (
                        item.region
                        for item in report.regions
                        if item.region.id == region_id
                    ),
                    None,
                )
                if region is None:
                    raise ValueError("unavailable")
                if region.molecule_id == key:
                    atoms, hydrogen_anchor = region.atom_indices, region.hydrogen_anchor
                else:
                    with queue.service.store.connect() as connection:
                        saved = connection.execute(
                            "SELECT payload FROM pairs WHERE job_id=? AND json_extract(payload,'$.region_id')=? AND json_extract(payload,'$.molecule_id')=? LIMIT 1",
                            (identifier, region_id, key),
                        ).fetchone()
                    if saved:
                        pair = Pair.model_validate_json(saved[0])
                        if pair.match_status == "matched":
                            atoms, hydrogen_anchor = (
                                pair.variable_atom_indices,
                                pair.candidate_hydrogen_anchor,
                            )
            svg = draw_molecule_preview(
                molecule.molfile,
                highlighted_atoms=atoms,
                hydrogen_anchor=hydrogen_anchor,
            )
        elif kind == "scaffold":
            scaffold = next(item for item in report.scaffolds if item.id == key)
            svg = draw_fragment(scaffold.smiles or "")
        elif kind == "fragment":
            region = next(
                item for item in report.regions if item.region.id == region_id
            )
            fragment = next(item for item in region.fragments if item.id == key)
            svg = draw_fragment(fragment.smiles, graph_smiles=fragment.graph_smiles)
        else:
            raise ValueError("unavailable")
    except (StopIteration, ValueError, RuntimeError) as error:
        raise WebError(
            422,
            "sar_structure_unavailable",
            "Study drawing is unavailable; no placeholder molecule was substituted.",
        ) from error
    return StudyDrawing(id=key, svg=svg)


def draw_batch(queue, identifier, job, report, kind, keys, region_id):
    items = []
    for key in keys:
        try:
            result = draw_one(queue, identifier, job, report, kind, key, region_id)
        except WebError as error:
            if error.status not in {404, 422}:
                raise
            items.append(
                StudyDrawingEntry(
                    identifier=key,
                    error=StudyDrawingError(
                        status=error.status, code=error.code, message=error.message
                    ),
                )
            )
        else:
            items.append(StudyDrawingEntry(identifier=key, result=result))
    result = StudyDrawingBatch(job=job, kind=kind, region_id=region_id, items=items)
    if len(result.model_dump_json().encode("utf-8")) > MAX_DRAWING_BATCH_BYTES:
        raise WebError(
            413,
            "sar_drawing_batch_large",
            "Drawing response exceeds the bounded batch size.",
        )
    return result
