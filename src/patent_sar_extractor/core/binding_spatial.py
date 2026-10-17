"""Original numbered-cell and exact-caption source authority."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import (
    Any,
)

from patent_sar_extractor.core.numbered_structure_binding import (
    NumberedTableResult,
    bind_numbered_tables,
)
from patent_sar_extractor.core.visible_structure_binding import bind_visible_captions

from .binding_candidates import (
    _active_ordered_bindings,
    _build_binding_from_structure,
    _normalise_binding_to_compound,
)
from .binding_labels import _binding_label_key
from .binding_types import (
    BindingCandidate,
    BindingConflict,
    SourceKind,
    SourceOwnership,
)
from .source_binding_proof import annotate_source_binding
from .structure_declarations import declaration_page_hint, observe_declaration_pages
from .table_geometry import detect_ruled_table_regions, page_tokens

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpatialBindings:
    candidates: tuple[BindingCandidate, ...]
    ownership: SourceOwnership
    conflicts: tuple[BindingConflict, ...]
    numbered_recognized: bool
    reprints: tuple[dict[str, Any], ...] = ()
    recognized_table_pages: frozenset[int] = frozenset()
    grids_for_page: Any = field(default=None, repr=False, compare=False)
    tokens_for_page: Any = field(default=None, repr=False, compare=False)
    source_sections: tuple[dict, ...] = ()

    def ordered(self, active_cpds: list[str]) -> list[dict[str, Any]]:
        if not active_cpds:
            return []
        return [
            annotate_source_binding(binding)
            for binding in _active_ordered_bindings(
                [dict(candidate.binding) for candidate in self.candidates], active_cpds
            )
        ]

    def catalogue(self) -> list[dict[str, Any]]:
        """Primary source ownership is printed-ID based, never activity-filtered."""
        return [
            annotate_source_binding(
                _normalise_binding_to_compound(
                    dict(candidate.binding), candidate.label_key
                )
            )
            for candidate in self.candidates
        ]

    def complete(self, active_cpds: list[str]) -> bool:
        bindings = self.ordered(active_cpds)
        return bool(
            active_cpds
            and len(bindings) == len(set(active_cpds))
            and len({binding["structure_id"] for binding in bindings}) == len(bindings)
            and all(
                binding.get("accuracy_status") == "confirmed"
                and not binding.get("fail_closed")
                for binding in bindings
            )
        )

    def structures(self, structures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            structure
            for structure in structures
            if int(structure["page_no"]) - 1 not in self.ownership.page_indices
            and str(structure["id"]) not in self.ownership.structure_ids
        ]

    def restore(
        self, bindings: list[dict[str, Any]], active_cpds: list[str]
    ) -> list[dict[str, Any]]:
        # Generic strategies cannot promote a withheld cell, reuse a claimed
        # segment, or substitute another source for an exact observed label.
        generic = [
            binding
            for binding in bindings
            if not self.ownership.protects(
                _binding_label_key(binding),
                str(binding.get("structure_id") or ""),
                int(binding.get("page_no") or 0) - 1,
            )
        ]
        return _active_ordered_bindings(
            [*self.ordered(active_cpds), *generic], active_cpds
        )


def _candidate(binding: dict[str, Any], source: SourceKind) -> BindingCandidate:
    return BindingCandidate(
        label_key=_binding_label_key(binding),
        structure_id=str(binding["structure_id"]),
        page_index=int(binding["page_no"]) - 1,
        source=source,
        binding=MappingProxyType(dict(binding)),
    )


def _resolve_claim_conflicts(
    candidates: list[BindingCandidate],
) -> tuple[tuple[BindingCandidate, ...], tuple[BindingConflict, ...]]:
    labels: dict[str, set[str]] = {}
    structures: dict[str, set[str]] = {}
    for candidate in candidates:
        labels.setdefault(candidate.label_key, set()).add(candidate.structure_id)
        structures.setdefault(candidate.structure_id, set()).add(candidate.label_key)
    accepted: dict[tuple[str, str], BindingCandidate] = {}
    conflicts = []
    for candidate in candidates:
        reason = (
            "ambiguous_compound_owner"
            if len(labels[candidate.label_key]) > 1
            else "ambiguous_structure_owner"
            if len(structures[candidate.structure_id]) > 1
            else None
        )
        if reason:
            conflicts.append(
                BindingConflict(candidate.label_key, candidate.page_index, reason)
            )
        else:
            accepted.setdefault(
                (candidate.label_key, candidate.structure_id), candidate
            )
    return tuple(accepted.values()), tuple(conflicts)


def collect_spatial_bindings(
    doc: Any,
    processed_structures: list[dict[str, Any]],
    pages_text: dict[int, str],
    line_map: dict[int, list[tuple[float, str]]],
    active_cpds: list[str],
    profile: dict[str, Any],
    table_pages: frozenset[int],
    *,
    source_pages: Sequence[int] | None = None,
) -> SpatialBindings:
    # Locator/classifier hints are not a complete table inventory. Discover
    # original numbered grids across every selected structure-source page;
    # the grid/header/cell authority still decides ownership, never this set.
    if source_pages is None:
        source_pages = [
            structure["page_no"] - 1
            for structure in processed_structures
            if type(structure.get("page_no")) is int
        ]
    candidate_pages = sorted(
        {
            page
            for page in (
                *table_pages,
                *source_pages,
                *(
                    index
                    for index, text in pages_text.items()
                    if declaration_page_hint(text)
                ),
            )
            if type(page) is int and page >= 0
        }
    )
    # Reuse observations only inside this immutable document call. The two
    # layout interpreters cannot start competing OCR passes or borrow a page
    # cache from a different PDF.
    grids, tokens = {}, {}

    def grids_for_page(page):
        if page.number not in grids:
            grids[page.number] = detect_ruled_table_regions(page, dpi=240)
        return grids[page.number]

    def tokens_for_page(page):
        if page.number not in tokens:
            tokens[page.number] = page_tokens(page, dpi=200, allow_tesseract=False)
        return tokens[page.number]

    numbered = bind_numbered_tables(
        doc,
        processed_structures,
        candidate_pages,
        None,
        grids_for_page=grids_for_page,
        tokens_for_page=tokens_for_page,
        page_texts=pages_text,
    )
    recognized_pages = set(numbered.recognized_pages)
    reserved_pages = set(numbered.ownership_pages)
    observed_keys = set(numbered.observed_keys)
    table_bindings = original_table_bindings(numbered)
    declaration_pages, nonfinal_declaration_ids = observe_declaration_pages(
        doc, processed_structures, candidate_pages, pages_text, tokens_for_page
    )
    candidates = [_candidate(binding, "numbered_cell") for binding in table_bindings]
    remaining = [
        structure
        for structure in processed_structures
        if int(structure["page_no"]) - 1 not in reserved_pages
        and str(structure["id"]) not in numbered.protected_structure_ids
        and str(structure["id"]) not in nonfinal_declaration_ids
    ]
    caption_issues = []
    caption_pages, protected_caption_ids, source_exclusions = set(), set(), []
    captions = bind_visible_captions(
        doc,
        remaining,
        None,
        excluded=frozenset(observed_keys),
        source_pages=[p for p in candidate_pages if p not in reserved_pages],
        recognized_pages=caption_pages,
        observed_labels=observed_keys,
        issues=caption_issues,
        source_exclusions=source_exclusions,
        protected_structure_ids=protected_caption_ids,
        grids_for_page=grids_for_page,
        tokens_for_page=tokens_for_page,
    )
    caption_ids = set()
    caption_keys = set()
    for pair in captions:
        binding = _build_binding_from_structure(pair.structure, pair.label)
        binding.update(
            {
                "binding_rule": "original_caption_cell",
                "visible_label": pair.label,
                "visible_label_candidates": [
                    {"label": pair.label, "source": "pdf_clip"}
                ],
                "visible_label_crop_source": "pdf_clip",
                "product_context_nearby": True,
                "product_context_distance": 0,
                "exact_caption_evidence": {
                    "bbox": list(pair.label_bbox),
                    "page_no": pair.label_page_no,
                    "ownership": pair.ownership,
                    "observations": pair.observations,
                },
            }
        )
        candidates.append(_candidate(binding, "exact_caption"))
        caption_ids.add(str(pair.structure["id"]))
        caption_keys.add(_binding_label_key(binding))
    accepted, conflicts = _resolve_claim_conflicts(candidates)
    reprints = []
    for pair in numbered.reprints:
        binding = _original_table_binding(pair, numbered.recognized_pages)
        reprints.append(
            annotate_source_binding(_normalise_binding_to_compound(binding, pair.label))
        )
    conflicts = (
        *conflicts,
        *(
            BindingConflict(
                issue["cpd"],
                issue["page_no"] - 1,
                issue["reason"],
                issue.get("evidence", {}),
            )
            for issue in caption_issues
        ),
        *(
            BindingConflict(
                issue.label, issue.page_index, issue.reason, dict(issue.evidence)
            )
            for issue in numbered.issues
        ),
    )
    ownership = SourceOwnership(
        page_indices=frozenset(reserved_pages),
        structure_ids=frozenset(
            caption_ids
            | protected_caption_ids
            | {candidate.structure_id for candidate in candidates}
            | {str(binding["structure_id"]) for binding in reprints}
            | numbered.protected_structure_ids
            | nonfinal_declaration_ids
        ),
        label_keys=frozenset(
            observed_keys
            | caption_keys
            | {candidate.label_key for candidate in candidates}
        ),
    )
    if conflicts:
        logger.warning("Original spatial source conflicts retained: %d", len(conflicts))
    return SpatialBindings(
        accepted,
        ownership,
        tuple(conflicts),
        numbered.recognized,
        tuple(reprints),
        frozenset(recognized_pages | caption_pages),
        grids_for_page,
        tokens_for_page,
        (*source_exclusions, *numbered.source_sections, *declaration_pages),
    )


def original_table_bindings(result: NumberedTableResult) -> list[dict[str, Any]]:
    return [
        _original_table_binding(pair, result.recognized_pages)
        for pair in result.bindings
    ]


def _original_table_binding(pair, table_pages):
    binding = _build_binding_from_structure(pair.structure, pair.label)
    evidence = pair.evidence()
    binding.update(
        {
            "binding_rule": "numbered_structure_table_cell",
            "numbered_table_cell_evidence": evidence,
            "authoritative_table_source_label": pair.label,
            "authoritative_table_pages": list(table_pages),
        }
    )
    header = (
        evidence.get("header_scope")
        if evidence.get("kind") == "original_unruled_columns"
        else (evidence.get("column_ownership") or {}).get("header_scope")
    )
    if header:
        binding["source_pdf_sha256"] = header["original_pdf_sha256"]
    return binding
