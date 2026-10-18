"""One document-wide ownership decision for original numbered/caption claims."""

from collections import defaultdict
from dataclasses import dataclass

from .binding_labels import _binding_label_key
from .binding_types import BindingCandidate, BindingConflict
from .caption_binding_proof import valid_caption_binding_evidence
from .numbered_structure_pairs import valid_cell_binding_evidence
from .structure_catalogs import (
    Catalog,
    catalog_for_caption_scope,
    catalog_for_scope,
    repeated_selected_catalogs,
)


@dataclass(frozen=True)
class _Claim:
    candidate: BindingCandidate
    catalog: Catalog

    @property
    def label(self):
        return self.candidate.label_key


@dataclass(frozen=True)
class SourceClaims:
    primary: tuple[BindingCandidate, ...]
    reprints: tuple[BindingCandidate, ...]
    conflicts: tuple[BindingConflict, ...]


def _catalog(candidate):
    binding = candidate.binding
    if candidate.source == "exact_caption" and valid_caption_binding_evidence(binding):
        owner = binding["exact_caption_evidence"]["ownership"]
        return catalog_for_caption_scope(owner.get("caption_role"))
    if candidate.source == "numbered_cell" and valid_cell_binding_evidence(binding):
        evidence = binding["numbered_table_cell_evidence"]
        scope = (
            evidence.get("header_scope")
            if evidence.get("kind") == "original_unruled_columns"
            else (evidence.get("column_ownership") or {}).get("header_scope")
        )
        return catalog_for_scope(scope)
    return Catalog()


def resolve_source_claims(
    candidates: list[BindingCandidate], *, retain_proposals=True
) -> SourceClaims:
    """A selected subset retains depictions, never guesses a primary or molecule."""
    claims = [_Claim(candidate, _catalog(candidate)) for candidate in candidates]
    repeated = repeated_selected_catalogs(claims)
    primary = [claim for claim in claims if claim.catalog.identifier not in repeated]
    labels, structures = defaultdict(set), defaultdict(set)
    for claim in primary:
        candidate = claim.candidate
        labels[candidate.label_key].add(candidate.structure_id)
    for candidate in candidates:
        structures[candidate.structure_id].add(candidate.label_key)
    accepted, reprints, conflicts = {}, {}, []

    def reject(candidate, reason):
        conflicts.append(
            BindingConflict(
                candidate.label_key,
                candidate.page_index,
                reason,
                {
                    "structure_id": candidate.structure_id,
                    "source": candidate.source,
                    **(
                        {"proposal": dict(candidate.binding)}
                        if retain_proposals
                        else {}
                    ),
                },
            )
        )

    for claim in primary:
        candidate = claim.candidate
        if len(labels[candidate.label_key]) > 1:
            reject(candidate, "ambiguous_compound_owner")
        elif len(structures[candidate.structure_id]) > 1:
            reject(candidate, "ambiguous_structure_owner")
        else:
            accepted.setdefault(
                (candidate.label_key, candidate.structure_id), candidate
            )
    proved_primary = {candidate.label_key for candidate in accepted.values()}
    for claim in claims:
        if claim.catalog.identifier not in repeated:
            continue
        candidate = claim.candidate
        if len(structures[candidate.structure_id]) > 1:
            reject(candidate, "ambiguous_structure_owner")
        elif candidate.label_key not in proved_primary:
            reject(candidate, "ambiguous_compound_owner")
        elif (candidate.label_key, candidate.structure_id) not in accepted:
            reprints.setdefault(
                (candidate.label_key, candidate.structure_id), candidate
            )
    return SourceClaims(
        tuple(accepted.values()), tuple(reprints.values()), tuple(conflicts)
    )


def validate_catalog_claims(entries):
    """Saved primary/additional labels cannot override original source roles."""
    candidates, primary, additional = [], set(), set()
    for entry in entries:
        for index, source in enumerate((entry, *entry.get("additional_sources", []))):
            rule = source.get("binding_rule")
            kind = (
                "numbered_cell"
                if rule == "numbered_structure_table_cell"
                else "exact_caption"
                if rule == "original_caption_cell"
                else "original_heading"
            )
            identity = source["structure_id"]
            (primary if index == 0 else additional).add(identity)
            candidates.append(
                BindingCandidate(
                    _binding_label_key(source),
                    identity,
                    source["page_no"] - 1,
                    kind,
                    {
                        key: value
                        for key, value in source.items()
                        if key != "additional_sources"
                    },
                )
            )
    result = resolve_source_claims(candidates, retain_proposals=False)
    if (
        result.conflicts
        or {item.structure_id for item in result.primary} != primary
        or {item.structure_id for item in result.reprints} != additional
    ):
        raise ValueError(
            "Saved source claims disagree with original catalogue ownership"
        )
