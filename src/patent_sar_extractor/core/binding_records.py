"""One bounded record collection; shape selection is not scientific admission."""

from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    MAX_RECOGNITION_SOURCES,
    schema_ref,
    schema_ref_matches,
)


def binding_records(payload, *, legacy=False):
    """Current records live only in the catalogue; archives retain explicit review.

    Callers must still validate artifact identity, catalogue ownership, original
    evidence and completeness. No flags or fallback here qualify a molecule.
    """
    if not isinstance(payload, dict):
        raise ValueError("Binding records require an artifact object")  # noqa: TRY004 -- shared artifact boundary
    current = schema_ref_matches(
        payload.get("schema"), schema_ref(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION)
    )
    catalog = payload.get("compound_catalog")
    if current:
        if "final_bindings" in payload or "bindings" in payload:
            raise ValueError("Current bindings contain a competing record authority")
        if not isinstance(catalog, dict):
            raise ValueError("Current bindings require the original source catalogue")
        rows = catalog.get("entries")
    elif legacy:
        # Explicit historical/diagnostic readers only. Formal acceptance has a
        # separate current-identity gate and can never promote these saved rows.
        rows = payload.get("final_bindings", payload.get("bindings"))
        if rows is None:
            rows = catalog.get("entries") if isinstance(catalog, dict) else []
    else:
        raise ValueError("Binding records do not have the current source identity")
    if (
        not isinstance(rows, list)
        or len(rows) > MAX_RECOGNITION_SOURCES
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise ValueError("Binding records must be a bounded ordered object list")
    if current:
        for count in (
            catalog.get("numbered_compounds"),
            payload.get("final_bindings_count", len(rows)),
        ):
            if type(count) is not int or count != len(rows):
                raise ValueError(
                    "Binding record count differs from the source catalogue"
                )
    return rows
