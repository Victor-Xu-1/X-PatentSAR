"""Strict saved records and exact-original, PUT-only corrupt-addon recovery."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .analysis_chemistry import canonical_smiles
from .correction_models import EditableFields
from .errors import WebError

_ADDONS = {"structure_molfile", "property_overrides", "property_basis_smiles"}


class CorruptCorrectionAddons(WebError):
    """GET still fails; only PUT may attempt the guarded exact-original reset."""

    def __init__(self) -> None:
        super().__init__(
            422, "invalid_correction", "Saved correction fields are invalid."
        )


def saved_fields(saved: dict[str, Any]) -> tuple[EditableFields, EditableFields]:
    try:
        baseline = EditableFields.model_validate_json(saved["original_fields"])
    except (ValidationError, ValueError, TypeError) as exc:
        raise WebError(
            422, "invalid_correction", "Saved correction fields are invalid."
        ) from exc
    try:
        values = EditableFields.model_validate_json(saved["fields"])
    except ValidationError as exc:
        errors = exc.errors(
            include_url=False, include_context=False, include_input=False
        )
        # The sole root value validator checks graph/basis addon consistency.
        # JSON/model-shape failures and invalid base fields are not a reset bypass.
        if errors and all(
            (error["loc"] and error["loc"][0] in _ADDONS)
            or (not error["loc"] and error["type"] == "value_error")
            for error in errors
        ):
            raise CorruptCorrectionAddons() from exc
        raise WebError(
            422, "invalid_correction", "Saved correction fields are invalid."
        ) from exc
    except (ValueError, TypeError) as exc:
        raise WebError(
            422, "invalid_correction", "Saved correction fields are invalid."
        ) from exc
    return baseline, values


def exact_original_reset(
    supplied: EditableFields, original: EditableFields
) -> EditableFields:
    try:
        fields = EditableFields.model_validate(supplied.model_dump())
    except ValidationError as exc:
        raise WebError(
            422, "invalid_correction", "Correction fields are invalid."
        ) from exc
    # Include scalar types and exact strings, not chemical equivalence or numeric
    # equality. Omitted addons take their safe defaults; never inherit corrupt data.
    if fields.model_dump_json() != original.model_dump_json():
        raise WebError(
            422,
            "invalid_correction",
            "Corrupt addons permit only an exact restoration of the original fields.",
        )
    return fields


def reset_needs_prediction(
    saved: dict[str, Any], source: str, smiles: str | None
) -> bool:
    # A stale overlay had no current graph authority. For current corrupt data,
    # do not guess its previous graph: enqueue the valid restored target. The
    # existing prediction worker safely reuses verified canonical cache records.
    if saved["basis_fingerprint"] != source or smiles is None:
        return False
    try:
        canonical_smiles(smiles)
    except WebError:
        # Exact rejected originals remain evidence, never new manual chemistry.
        return False
    return True
