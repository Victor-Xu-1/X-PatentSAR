"""One document-wide ownership decision for original numbered/caption claims."""

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .binding_labels import _binding_label_key
from .binding_types import BindingCandidate, BindingConflict, SourceKind
from .caption_binding_proof import valid_caption_binding_evidence
from .compound_caption import caption_namespace
from .heading_evidence import valid_heading_binding_evidence
from .heading_source_proof import proved_heading_declaration
from .numbered_structure_pairs import valid_cell_binding_evidence
from .printed_identifiers import label_kind_namespace
from .source_cell_claims import cell_source_status
from .structure_catalogs import (
    Catalog,
    catalog_for_caption_scope,
    catalog_for_scope,
    repeated_selected_catalogs,
)

_SOURCE_KINDS: dict[str, SourceKind] = {
    "numbered_structure_table_cell": "numbered_cell",
    "original_caption_cell": "exact_caption",
    "original_heading_standalone": "original_heading",
}


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


def source_candidate(source: Mapping[str, Any]) -> BindingCandidate:
    """One original-rule adapter for the writer and saved source-claim replay."""
    kind = _SOURCE_KINDS.get(source.get("binding_rule"))
    if kind is None:
        raise ValueError("Unsupported original source claim")
    return BindingCandidate(
        _binding_label_key(source),
        str(source["structure_id"]),
        source["page_no"] - 1,
        kind,
        {k: v for k, v in source.items() if k != "additional_sources"},
    )


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


def _heading_references(claims, repeated):
    """Explicit preparation declarations may repeat one known catalogue owner.

    Same numeric text alone is insufficient. Both source proofs must hold, the
    original document and literal ID namespace must agree, and a unique primary
    catalogue must actually contain that label. Chemistry is checked downstream
    for EVERY retained depiction; this relation does not certify any molecule.
    """
    headings = [
        claim for claim in claims if claim.candidate.source == "original_heading"
    ]
    if not headings:
        return set(), set()
    wanted = {claim.label for claim in headings}
    catalogues, known_labels = defaultdict(set), set()
    for claim in claims:
        catalog, candidate = claim.catalog, claim.candidate
        if candidate.source != "original_heading":
            known_labels.add(claim.label)
        original = candidate.binding.get("source_pdf_sha256")
        if (
            catalog.identifier
            and claim.label in wanted
            and catalog.identifier not in repeated
            and catalog.namespace
            and original
            and _consistent_cell_namespace(candidate, catalog.namespace)
        ):
            catalogues[(claim.label, catalog.namespace, original)].add(
                catalog.identifier
            )
    references, unresolved = set(), set()
    for claim in headings:
        candidate, binding = claim.candidate, claim.candidate.binding
        if not valid_heading_binding_evidence(binding):
            continue
        declaration = proved_heading_declaration(
            binding["original_heading_structure_evidence"]["heading_source"]
        )
        namespace = label_kind_namespace(declaration["label_kind"])
        key = (claim.label, namespace, binding.get("source_pdf_sha256"))
        if namespace and len(catalogues.get(key, ())) == 1:
            references.add((claim.label, candidate.structure_id))
        elif claim.label in known_labels:
            # Keep the already-proved physical catalogue anchor for its ledger,
            # but do not invent a cross-namespace alias. This separate occurrence
            # is retained as an unresolved diagnostic and blocks final acceptance.
            unresolved.add((claim.label, candidate.structure_id))
    return references, unresolved


def _consistent_cell_namespace(candidate, expected):
    field = (
        "exact_caption_evidence"
        if candidate.source == "exact_caption"
        else "numbered_table_cell_evidence"
    )
    evidence = candidate.binding[field]
    observations = (
        evidence["row_label"]["observations"]
        if evidence.get("kind") == "original_unruled_columns"
        else evidence["observations"]
    )
    for observation in observations:
        method = observation.get("method", "")
        if method in {"native_cell", "page_ocr_cell"}:
            if cell_source_status(observation) != "qualified":
                continue
        elif method.startswith("cell_ocr_"):
            score = observation.get("confidence")
            if (
                type(score) not in {int, float}
                or not math.isfinite(score)
                or not 0.85 <= score <= 1
            ):
                continue
        else:
            continue
        for raw in (observation.get("text"), observation.get("raw_text")):
            namespace = caption_namespace(str(raw or ""))
            if namespace and namespace != expected:
                return False
    return True


def resolve_source_claims(
    candidates: list[BindingCandidate], *, retain_proposals=True
) -> SourceClaims:
    """A selected subset retains depictions, never guesses a primary or molecule."""
    claims = [_Claim(candidate, _catalog(candidate)) for candidate in candidates]
    repeated = repeated_selected_catalogs(claims)
    heading_references, unresolved_headings = _heading_references(claims, repeated)

    def reference(claim):
        return (
            claim.catalog.identifier in repeated
            or (claim.label, claim.candidate.structure_id) in heading_references
        )

    primary = [
        claim
        for claim in claims
        if not reference(claim)
        and (claim.label, claim.candidate.structure_id) not in unresolved_headings
    ]
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

    for claim in claims:
        if (claim.label, claim.candidate.structure_id) in unresolved_headings:
            reject(claim.candidate, "unresolved_heading_reference")

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
        if not reference(claim):
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
            identity = source["structure_id"]
            (primary if index == 0 else additional).add(identity)
            candidates.append(source_candidate(source))
    result = resolve_source_claims(candidates, retain_proposals=False)
    if (
        result.conflicts
        or {item.structure_id for item in result.primary} != primary
        or {item.structure_id for item in result.reprints} != additional
    ):
        raise ValueError(
            "Saved source claims disagree with original catalogue ownership"
        )
