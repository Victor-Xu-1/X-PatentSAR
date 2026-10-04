"""Compatibility preparation for source-bound editable-field overlays."""

from __future__ import annotations

from .correction_chemistry import same_graph
from .correction_models import EditableFields

_ADDONS: dict[str, object] = {
    "structure_molfile": None,
    "property_overrides": {},
    "property_basis_smiles": None,
}


def prepared_fields(supplied: EditableFields, before: EditableFields) -> EditableFields:
    data = supplied.model_dump()
    unchanged = same_graph(before.smiles, supplied.smiles)
    for key, cleared in _ADDONS.items():
        if key not in supplied.model_fields_set:
            data[key] = getattr(before, key) if unchanged else cleared
    # Revalidate internal model_copy callers, as well as old-client inherited fields.
    return EditableFields.model_validate(data)
