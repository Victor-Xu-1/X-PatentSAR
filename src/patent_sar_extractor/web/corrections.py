"""Transactional manual overlays, separate from model evidence and formal QA."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .analysis_chemistry import canonical_smiles
from .correction_chemistry import same_graph, same_structure
from .correction_fields import prepared_fields
from .correction_models import CorrectionDocument, CorrectionRequest, EditableFields
from .correction_recovery import (
    CorruptCorrectionAddons,
    exact_original_reset,
    reset_needs_prediction,
    saved_fields,
)
from .correction_storage import (
    CorrectionStorage,
    correction_source_fingerprint,
    correction_view_fingerprint,
)
from .errors import WebError
from .models import Compound, CorrectionMetadata, Recognition
from .molecule_drawing import drawing_url
from .prediction_identity import (
    compound_prediction_eligible,
    prediction_eligible,
    source_stereo_blocked,
)
from .recognition_storage import apply_recognition
from .storage import Store, now

CorrectionSaved = Callable[[sqlite3.Connection, str, str, Compound], None]


def original_fields(compound: Compound) -> EditableFields:
    try:
        return EditableFields(
            display_id=compound.display_id,
            smiles=compound.smiles,
            activities=compound.activities,
        )
    except ValidationError as exc:
        raise WebError(
            422,
            "correction_limit",
            "Original row exceeds the supported correction limits.",
        ) from exc


def apply_correction(
    project: dict[str, Any],
    row: dict[str, Any],
    saved: dict[str, Any] | None,
    compound: Compound,
) -> Compound:
    if saved is None:
        return compound
    baseline, values = saved_fields(saved)
    stale = saved["basis_fingerprint"] != correction_source_fingerprint(project, row)
    changed = values != baseline
    compound.correction = CorrectionMetadata(
        revision=saved["revision"],
        stale=stale,
        has_changes=changed,
        updated_at=saved["updated_at"],
    )
    if stale or not changed:
        return compound
    original_smiles = compound.smiles
    original_molfile = compound.structure_molfile
    blocked_original = source_stereo_blocked(compound)
    compound.display_id = values.display_id
    compound.activities = values.activities
    graph_edited = (
        values.smiles != baseline.smiles
        or values.structure_molfile != baseline.structure_molfile
    )
    if graph_edited:
        compound.smiles = values.smiles
        compound.structure_molfile = values.structure_molfile
    compound.property_overrides = dict(values.property_overrides)
    compound.property_basis_smiles = values.property_basis_smiles
    if not graph_edited and not same_graph(values.smiles, compound.smiles):
        # A new model graph cannot silently reassociate old graph-less overrides.
        compound.property_overrides = {}
        compound.property_basis_smiles = None
    compound.flags = [*compound.flags, "manual_correction"]
    if graph_edited and (
        values.smiles != original_smiles or values.structure_molfile != original_molfile
    ):
        # A view-level producer record must be rechecked against the current
        # representation; original persisted observations remain untouched.
        compound.admet = None
        if values.smiles is not None:
            # Private persistence is still an input boundary. A corrupted
            # overlay cannot acquire manual-valid recognition on a later read.
            canonical_smiles(values.smiles)
        ambiguous = (
            not prediction_eligible(values.smiles, values.structure_molfile)
            if values.smiles
            else False
        )
        if ambiguous:
            compound.flags = [*compound.flags, "manual_stereo_unresolved"]
        if not blocked_original or not same_graph(original_smiles, values.smiles):
            compound.recognition = Recognition(
                status="valid" if values.smiles else "not_run",
                quality_flag="manual_stereo_unresolved"
                if ambiguous
                else "manual_correction",
            )
        compound.redraw_image_url = (
            drawing_url(
                project["id"], compound.id, values.smiles, values.structure_molfile
            )
            if values.smiles
            else None
        )
    return compound


class Corrections:
    def __init__(
        self,
        store: Store,
        current_project: Callable[[str], dict[str, Any]],
        *,
        on_save: CorrectionSaved | None = None,
    ) -> None:
        self.store = store
        self.storage = CorrectionStorage(store)
        self.current_project = current_project
        self.on_save = on_save
        self.after_save: Callable[[str], None] | None = None

    @staticmethod
    def _document(
        project: dict[str, Any], row: dict[str, Any], saved: dict[str, Any] | None
    ) -> CorrectionDocument:
        compound = apply_recognition(
            project, row, Compound.model_validate_json(row["payload"])
        )
        original = original_fields(compound)
        fingerprint = correction_source_fingerprint(project, row)
        baseline, values = saved_fields(saved) if saved else (original, original)
        changed = values != baseline
        if saved and saved["basis_fingerprint"] == fingerprint:
            values = (
                original_fields(apply_correction(project, row, saved, compound))
                if values == baseline
                else values
            )
            if (
                values.smiles == baseline.smiles
                and values.structure_molfile == baseline.structure_molfile
            ):
                updates = {"smiles": original.smiles}
                if not same_graph(values.smiles, original.smiles):
                    updates.update(property_overrides={}, property_basis_smiles=None)
                values = EditableFields.model_validate(
                    {**values.model_dump(), **updates}
                )
        return CorrectionDocument(
            source_fingerprint=correction_view_fingerprint(project, row, compound),
            revision=saved["revision"] if saved else 0,
            basis_fingerprint=saved["basis_fingerprint"] if saved else None,
            stale=bool(saved and saved["basis_fingerprint"] != fingerprint),
            has_changes=changed,
            original=original,
            values=values,
            updated_at=saved["updated_at"] if saved else None,
        )

    def get(self, project_id: str, compound_id: str) -> CorrectionDocument:
        self.current_project(project_id)
        with self.store.connect() as connection:
            connection.execute("BEGIN")
            return self._document(
                *self.storage.context(connection, project_id, compound_id)
            )

    def compound(self, project_id: str, compound_id: str) -> Compound:
        self.current_project(project_id)
        with self.store.connect() as connection:
            connection.execute("BEGIN")
            project, row, saved = self.storage.context(
                connection, project_id, compound_id
            )
            return apply_correction(
                project,
                row,
                saved,
                apply_recognition(
                    project, row, Compound.model_validate_json(row["payload"])
                ),
            )

    def put(
        self, project_id: str, compound_id: str, request: CorrectionRequest
    ) -> CorrectionDocument:
        self.current_project(project_id)
        with self.store.connect(write=True) as connection:
            project, row, saved = self.storage.context(
                connection, project_id, compound_id
            )
            if connection.execute(
                "SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",
                (project_id,),
            ).fetchone():
                raise WebError(
                    409,
                    "correction_busy",
                    "Finish the active project task before editing results.",
                )
            revision = saved["revision"] if saved else 0
            fingerprint = correction_source_fingerprint(project, row)
            base = apply_recognition(
                project, row, Compound.model_validate_json(row["payload"])
            )
            edit_fingerprint = correction_view_fingerprint(project, row, base)
            if request.expected_revision != revision:
                raise WebError(
                    409,
                    "correction_conflict",
                    "Correction changed; refresh before saving.",
                )
            if request.expected_source_fingerprint != edit_fingerprint:
                raise WebError(
                    409,
                    "correction_source_conflict",
                    "Source results changed; refresh before saving.",
                )
            try:
                document = self._document(project, row, saved)
            except CorruptCorrectionAddons:
                assert saved is not None
                original = original_fields(
                    apply_recognition(
                        project, row, Compound.model_validate_json(row["payload"])
                    )
                )
                fields = exact_original_reset(request.fields, original)
                needs_prediction = reset_needs_prediction(
                    saved, fingerprint, fields.smiles
                )
            else:
                original = document.original
                # Revalidate internal model_copy callers as well as HTTP input.
                try:
                    before = (
                        document.values
                        if document.has_changes and not document.stale
                        else original
                    )
                    fields = prepared_fields(request.fields, before)
                except ValidationError as exc:
                    raise WebError(
                        422, "invalid_correction", "Correction fields are invalid."
                    ) from exc
                needs_prediction = not same_structure(
                    before.smiles,
                    fields.smiles,
                    before.structure_molfile,
                    fields.structure_molfile,
                )
            original_pages = {a.page for a in original.activities if a.page}
            if fields.activities != original.activities and any(
                a.page
                and (
                    a.page > project["page_count"]
                    if project["page_count"]
                    else a.page not in original_pages
                )
                for a in fields.activities
            ):
                raise WebError(
                    422,
                    "correction_page",
                    "Activity page is outside the known original document.",
                )
            if fields.smiles is not None and fields.smiles != original.smiles:
                # Validate, but never guess/repair/rewrite the operator's string.
                # An exact reset retains original evidence, including a rejected
                # raw model string, without promoting it to manual validation.
                canonical_smiles(fields.smiles)
            result = CorrectionDocument(
                source_fingerprint=edit_fingerprint,
                revision=revision + 1,
                basis_fingerprint=fingerprint,
                stale=False,
                has_changes=fields != original,
                original=original,
                values=fields,
                updated_at=now(),
            )
            self.storage.write(connection, project_id, compound_id, result)
            _, _, updated = self.storage.context(connection, project_id, compound_id)
            effective = apply_correction(
                project,
                row,
                updated,
                apply_recognition(
                    project, row, Compound.model_validate_json(row["payload"])
                ),
            )
            if (
                self.on_save is not None
                and needs_prediction
                and compound_prediction_eligible(effective)
            ):
                # Same connection and transaction: a failed durable enqueue
                # rolls back the overlay AND audit, never a half-saved molecule.
                self.on_save(connection, project_id, compound_id, effective)
        if self.after_save is not None:
            self.after_save(project_id)
        return result
