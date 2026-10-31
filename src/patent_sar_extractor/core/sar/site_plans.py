"""Lightweight original-order proposals; candidate lists materialize on demand."""

import hashlib
from dataclasses import dataclass

from ..identifier_order import natural_identifier_key
from .matching import compile_reference


@dataclass(frozen=True, slots=True)
class SiteProposal:
    molecule_id: str
    atoms: tuple[int, ...]
    ports: int
    hydrogen_anchor: int | None
    region_id: str
    ordinal: int
    members: tuple[str, ...]


def ordered_site_plans(
    families, rows, identities, dataset, manual_regions, pool, check, excluded
):
    """Smallest regions first for proof, retaining the prior stable source order.

    At most one small proposal per already-bounded indexed cut is stored. The
    repeated candidate-ID vectors are allocated only as the reducer requests a
    plan; they never form an unbounded raw comparison matrix.
    """
    by_id = {row["id"]: row for row in rows}
    order = {
        row["id"]: (natural_identifier_key(row["label"]), row["id"]) for row in rows
    }
    manual = {
        (
            region["molecule_id"],
            tuple(sorted(region["atom_indices"])),
            region.get("hydrogen_anchor"),
        )
        for region in manual_regions
    }
    proposals = []
    for key, indexed in sorted(families.items()):
        check()
        if len(indexed) < 2:
            continue
        excluded["ambiguous_cut_location"] += sum(
            not atoms for atoms in indexed.values()
        )
        members = tuple(
            sorted(
                (mid for mid, atoms in indexed.items() if atoms), key=order.__getitem__
            )
        )
        for mid in members:
            check()
            selection, ports, hydrogen_anchor = indexed[mid]
            if (
                not any(identities[other] != identities[mid] for other in members)
                or (mid, tuple(sorted(selection)), hydrogen_anchor) in manual
            ):
                continue
            try:
                compile_reference(
                    by_id[mid]["molfile"],
                    selection,
                    hydrogen_anchor=hydrogen_anchor,
                    pool=pool,
                )
            except ValueError:
                excluded["unsupported_reference_boundary"] += 1
                continue
            seed = "\0".join(
                (
                    dataset["id"],
                    str(dataset["revision"]),
                    mid,
                    by_id[mid]["graph_sha256"],
                    key,
                    ",".join(map(str, selection)),
                    "ordinary_hydrogen:" + str(hydrogen_anchor)
                    if hydrogen_anchor is not None
                    else "original_atoms",
                )
            )
            proposals.append(
                SiteProposal(
                    mid,
                    selection,
                    ports,
                    hydrogen_anchor,
                    hashlib.sha256(seed.encode()).hexdigest()[:32],
                    len(proposals),
                    members,
                )
            )
    for proposal in sorted(proposals, key=lambda p: (len(p.atoms), p.region_id)):
        check()
        yield {
            "region": {
                "id": proposal.region_id,
                "dataset_id": dataset["id"],
                "dataset_revision": dataset["revision"],
                "molecule_id": proposal.molecule_id,
                "graph_sha256": by_id[proposal.molecule_id]["graph_sha256"],
                "atom_indices": list(proposal.atoms),
                "hydrogen_anchor": proposal.hydrogen_anchor,
                "attachment_count": proposal.ports,
                "kind": "variable",
                "name": f"S{proposal.ordinal + 1}",
                "created_at": dataset.get("created_at", "source-derived"),
            },
            "candidate_ids": [
                mid
                for mid in proposal.members
                if mid != proposal.molecule_id
                and identities[mid] != identities[proposal.molecule_id]
            ],
        }
