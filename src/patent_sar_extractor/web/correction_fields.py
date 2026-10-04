"""Compatibility preparation for source-bound editable-field overlays."""

from __future__ import annotations

from .correction_chemistry import same_graph, same_structure
from .correction_models import EditableFields

_PROPERTY_ADDONS: dict[str, object] = {
    "property_overrides": {},
    "property_basis_smiles": None,
}


def prepared_fields(supplied: EditableFields, before: EditableFields) -> EditableFields:
    data = supplied.model_dump()
    if "structure_molfile" not in supplied.model_fields_set:
        data["structure_molfile"] = (
            before.structure_molfile
            if same_graph(before.smiles, supplied.smiles)
            else None
        )
    unchanged = same_structure(
        before.smiles,
        supplied.smiles,
        before.structure_molfile,
        data["structure_molfile"],
    )
    for key, cleared in _PROPERTY_ADDONS.items():
        if key not in supplied.model_fields_set:
            data[key] = getattr(before, key) if unchanged else cleared
    # Revalidate internal model_copy callers, as well as old-client inherited fields.
    return EditableFields.model_validate(data)
