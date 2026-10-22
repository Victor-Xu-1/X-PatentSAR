"""Lossless opt-in catalog serialization, never a second report producer."""

from typing import Annotated, Literal

from pydantic import Field

from .study_catalog_models import (
    CatalogFragment,
    CatalogRegion,
    CatalogReport,
    StudyCatalog,
)

Index = Annotated[int, Field(strict=True, ge=0)]


class PooledFragment(CatalogFragment):
    molecule_ids: Index


class PooledRegion(CatalogRegion):
    fragments: list[Index]


class PooledReport(CatalogReport):
    regions: list[PooledRegion]


class PooledCatalog(StudyCatalog):
    detail: Literal["catalog-pooled"] = "catalog-pooled"
    wire_version: Literal[1] = 1
    report: PooledReport
    fragment_pool: list[PooledFragment]
    molecule_id_pool: list[list[str]]


def pooled_catalog(catalog: StudyCatalog) -> StudyCatalog | PooledCatalog:
    """Pool complete entries and ordered members; keep legacy when it is smaller.

    All other fields are inherited, not reconstructed from a field allowlist.
    Canonical complete JSON keys include every fragment field (not just its ID).
    Pools are request-local and contain no scientific calculation or cache.
    """
    members: list[list[str]] = []
    fragments: list[PooledFragment] = []
    regions: list[PooledRegion] = []
    member_index: dict[tuple[str, ...], int] = {}
    fragment_index: dict[str, int] = {}
    old_bytes = new_bytes = 0
    for region in catalog.report.regions:
        refs: list[int] = []
        for fragment in region.fragments:
            key = fragment.model_dump_json()
            old_bytes += len(key.encode("utf-8"))
            index = fragment_index.get(key)
            if index is None:
                member_key = tuple(fragment.molecule_ids)
                member = member_index.get(member_key)
                if member is None:
                    member = len(members)
                    member_index[member_key] = member
                    members.append(list(member_key))
                index = len(fragments)
                fragment_index[key] = index
                fragments.append(
                    PooledFragment.model_validate(
                        {**fragment.model_dump(), "molecule_ids": member}
                    )
                )
            refs.append(index)
            new_bytes += len(str(index))
        # Each nonempty fragment array has the same number of commas either way.
        regions.append(
            PooledRegion.model_validate({**region.model_dump(), "fragments": refs})
        )
    result = PooledCatalog(
        job=catalog.job,
        activity_basis=catalog.activity_basis,
        report=PooledReport.model_validate(
            {**catalog.report.model_dump(exclude={"regions"}), "regions": regions}
        ),
        fragment_pool=fragments,
        molecule_id_pool=members,
    )
    # Exact additive JSON cost; no second full legacy serialization is needed.
    pool_json = result.model_dump_json(
        include={"wire_version", "fragment_pool", "molecule_id_pool"}
    )
    overhead = len(pool_json.encode("utf-8")) - 1  # replace {} with a separating comma
    overhead += len("catalog-pooled") - len("catalog")
    return result if new_bytes + overhead < old_bytes else catalog
