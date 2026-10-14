"""One native/cached reference catalog, independent of physical table success."""

from .activity_coverage import source_record
from .activity_source_discovery import reference_observations


def observe_result_references(page_no: int, original_texts: list[str]) -> list[dict]:
    catalogs = [reference_observations(text) for text in original_texts]
    signatures = [
        [
            (item["status"], tuple(target.casefold() for target in item["targets"]))
            for item in catalog
        ]
        for catalog in catalogs
    ]
    agreement = signatures and all(item == signatures[0] for item in signatures)
    records = {}
    for catalog in catalogs[:1] if agreement else catalogs:
        for item in catalog:
            record = source_record(
                page_no,
                "page",
                None,
                "",
                item["header"],
                item["status"] if agreement else "unresolved",
                item["reason"] if agreement else "conflicting_result_references",
                0,
            )
            records[record["region_id"]] = record
    return list(records.values())
