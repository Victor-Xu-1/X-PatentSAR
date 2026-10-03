"""Read and recheck the single produced printed-ID catalog, never bind in the UI."""

from __future__ import annotations

from typing import Any

from patent_sar_extractor.contracts import (
    COMPOUND_CATALOG_SCHEMA,
    COMPOUND_CATALOG_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.core.pipeline_rules import (
    _label_key,
    annotate_binding_accuracy,
)

from .errors import WebError
from .files import MAX_RECORDS


def _checked_source(source: dict[str, Any]) -> dict[str, Any]:
    candidates = source.get("visible_label_candidates", [])
    if (
        not isinstance(candidates, list)
        or len(candidates) > 1000
        or any(not isinstance(candidate, dict) for candidate in candidates)
    ):
        raise WebError(
            422,
            "invalid_compound_catalog",
            "Printed-ID label observations are invalid.",
        )
    try:
        return annotate_binding_accuracy(dict(source))
    except (TypeError, ValueError, OverflowError, AttributeError) as exc:
        raise WebError(
            422, "invalid_compound_catalog", "Printed-ID source proof is malformed."
        ) from exc


def read_compound_catalog(
    payload: dict[str, Any], structures: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, set[str]]:
    catalog = payload.get("compound_catalog")
    if catalog is None:
        return None, set()
    if (
        not isinstance(catalog, dict)
        or catalog.get("schema")
        != schema_ref(COMPOUND_CATALOG_SCHEMA, COMPOUND_CATALOG_SCHEMA_VERSION)
        or type(catalog["schema"]["version"]) is not int
        or catalog.get("authority")
        != "printed_identifier_and_original_spatial_evidence"
    ):
        raise WebError(
            422,
            "invalid_compound_catalog",
            "Printed-ID catalog identity is not supported.",
        )
    entries = catalog.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_RECORDS:
        raise WebError(
            422,
            "invalid_compound_catalog",
            "Printed-ID catalog entries are missing or excessive.",
        )
    known = {str(item.get("structure_id") or "") for item in structures}
    labels, owned, alias_ids = set(), set(), set()
    output = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise WebError(
                422, "invalid_compound_catalog", "Printed-ID catalog row is invalid."
            )
        checked = _checked_source(raw)
        key = _label_key(str(checked.get("cpd") or checked.get("compound_id") or ""))
        structure_id = str(checked.get("structure_id") or "")
        if (
            not key
            or key in labels
            or not structure_id
            or structure_id not in known
            or structure_id in owned
            or checked.get("accuracy_status") != "confirmed"
            or checked.get("fail_closed")
        ):
            raise WebError(
                422,
                "invalid_compound_catalog",
                "Primary ID/crop ownership is not independently confirmed.",
            )
        labels.add(key)
        owned.add(structure_id)
        additional = checked.get("additional_sources", [])
        if not isinstance(additional, list) or len(additional) > 1000:
            raise WebError(
                422,
                "invalid_compound_catalog",
                "Additional source collection is invalid.",
            )
        for source in additional:
            if not isinstance(source, dict):
                raise WebError(
                    422, "invalid_compound_catalog", "Additional source is invalid."
                )
            proof = _checked_source(source)
            alias = str(proof.get("structure_id") or "")
            if (
                _label_key(str(proof.get("cpd") or proof.get("compound_id") or ""))
                != key
                or alias not in known
                or alias in owned
                or proof.get("accuracy_status") != "confirmed"
                or proof.get("fail_closed")
            ):
                raise WebError(
                    422,
                    "invalid_compound_catalog",
                    "Reprint does not prove the same printed owner.",
                )
            owned.add(alias)
            alias_ids.add(alias)
        output.append(checked)
    return output, alias_ids
