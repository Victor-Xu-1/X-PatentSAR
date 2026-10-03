"""Transactional manual overlays, separate from model evidence and formal QA."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .analysis_chemistry import canonical_smiles
from .correction_models import CorrectionDocument, CorrectionRequest, EditableFields
from .correction_storage import CorrectionStorage, correction_source_fingerprint
from .errors import WebError
from .models import Compound, CorrectionMetadata, Recognition
from .molecule_drawing import drawing_url
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


def _saved_fields(saved: dict[str, Any]) -> tuple[EditableFields, EditableFields]:
    try:
        return (
            EditableFields.model_validate_json(saved["original_fields"]),
            EditableFields.model_validate_json(saved["fields"]),
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise WebError(
            422, "invalid_correction", "Saved correction fields are invalid."
        ) from exc


def apply_correction(
    project: dict[str, Any],
    row: dict[str, Any],
    saved: dict[str, Any] | None,
    compound: Compound,
) -> Compound:
    if saved is None:
        return compound
    baseline, values = _saved_fields(saved)
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
    compound.display_id = values.display_id
    compound.smiles = values.smiles
    compound.activities = values.activities
    compound.flags = [*compound.flags, "manual_correction"]
    if values.smiles != original_smiles:
        if values.smiles is not None:
            # Private persistence is still an input boundary. A corrupted
            # overlay cannot acquire manual-valid recognition on a later read.
            canonical_smiles(values.smiles)
        compound.recognition = Recognition(
            status="valid" if values.smiles else "not_run",
            quality_flag="manual_correction",
        )
        compound.redraw_image_url = (
            drawing_url(project["id"], compound.id, values.smiles)
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

    @staticmethod
    def _document(
        project: dict[str, Any], row: dict[str, Any], saved: dict[str, Any] | None
    ) -> CorrectionDocument:
        original = original_fields(Compound.model_validate_json(row["payload"]))
        fingerprint = correction_source_fingerprint(project, row)
        baseline, values = _saved_fields(saved) if saved else (original, original)
        return CorrectionDocument(
            source_fingerprint=fingerprint,
            revision=saved["revision"] if saved else 0,
            basis_fingerprint=saved["basis_fingerprint"] if saved else None,
            stale=bool(saved and saved["basis_fingerprint"] != fingerprint),
            has_changes=values != baseline,
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
                project, row, saved, Compound.model_validate_json(row["payload"])
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
            document = self._document(project, row, saved)
            if request.expected_revision != document.revision:
                raise WebError(
                    409,
                    "correction_conflict",
                    "Correction changed; refresh before saving.",
                )
            if request.expected_source_fingerprint != document.source_fingerprint:
                raise WebError(
                    409,
                    "correction_source_conflict",
                    "Source results changed; refresh before saving.",
                )
            # Revalidate even internal model_copy callers; API validation is not
            # the transaction's only input boundary.
            try:
                fields = EditableFields.model_validate(request.fields.model_dump())
            except ValidationError as exc:
                raise WebError(
                    422, "invalid_correction", "Correction fields are invalid."
                ) from exc
            original_pages = {a.page for a in document.original.activities if a.page}
            if fields.activities != document.original.activities and any(
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
            if fields.smiles is not None and fields.smiles != document.original.smiles:
                # Validate, but never guess/repair/rewrite the operator's string.
                # An exact reset retains original evidence, including a rejected
                # raw model string, without promoting it to manual validation.
                canonical_smiles(fields.smiles)
            before_smiles = (
                document.values.smiles
                if document.has_changes and not document.stale
                else document.original.smiles
            )
            result = CorrectionDocument(
                source_fingerprint=document.source_fingerprint,
                revision=document.revision + 1,
                basis_fingerprint=document.source_fingerprint,
                stale=False,
                has_changes=fields != document.original,
                original=document.original,
                values=fields,
                updated_at=now(),
            )
            self.storage.write(connection, project_id, compound_id, result)
            _, _, updated = self.storage.context(connection, project_id, compound_id)
            effective = apply_correction(
                project, row, updated, Compound.model_validate_json(row["payload"])
            )
            if self.on_save is not None and before_smiles != effective.smiles:
                # Same connection and transaction: a failed durable enqueue
                # rolls back the overlay AND audit, never a half-saved molecule.
                self.on_save(connection, project_id, compound_id, effective)
        return result
