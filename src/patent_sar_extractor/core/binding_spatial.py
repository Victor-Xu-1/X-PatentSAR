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
from .binding_progress import BindingObserver
from .binding_source_claims import resolve_source_claims
from .binding_types import (
    BindingCandidate,
    BindingConflict,
    SourceKind,
    SourceOwnership,
)
from .caption_grid_binding import bind_caption_grids
from .numbered_structure_pairs import _box
from .source_binding_proof import annotate_source_binding
from .structure_declarations import observe_declaration_pages
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
    progress: BindingObserver | None = None,
) -> SpatialBindings:
    # Locator/classifier hints are not a complete table inventory. Discover
    # original numbered grids across the complete existing page-text inventory.
    # A headerless next page can lack both a new declaration and detector hits.
    # The observer inspects adjacent registered sources but skips unrelated prose
    # before coordinate OCR; membership in this set never authorizes ownership.
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
                *pages_text,
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
            grids[page.number] = detect_ruled_table_regions(
                page, dpi=240, minimum_columns=1
            )
        return grids[page.number]

    def tokens_for_page(page):
        if page.number not in tokens:
            tokens[page.number] = page_tokens(page, dpi=200, allow_tesseract=False)
        return tokens[page.number]

    # One complete caption observation precedes header-role admission. A continued
    # caption frame must not become an unrelated unruled-header candidate first.
    caption_structures = {}
    for structure in processed_structures:
        caption_structures.setdefault(structure["page_no"], []).append(structure)
    caption_boxes = {
        page: [
            _box([row.get(axis) for axis in ("x0", "y0", "x1", "y1")]) for row in rows
        ]
        for page, rows in caption_structures.items()
    }
    caption_grids = bind_caption_grids(
        doc,
        caption_structures,
        caption_boxes,
        [page + 1 for page in candidate_pages],
        grids_for_page=grids_for_page,
        tokens_for_page=tokens_for_page,
        progress=progress,
    )
    numbered = bind_numbered_tables(
        doc,
        processed_structures,
        candidate_pages,
        None,
        grids_for_page=grids_for_page,
        tokens_for_page=tokens_for_page,
        page_texts=pages_text,
        caption_roles=caption_grids.roles,
        progress=progress,
    )
    recognized_pages = set(numbered.recognized_pages)
    reserved_pages = set(numbered.ownership_pages)
    observed_keys = set(numbered.observed_keys)
    table_bindings = [
        *original_table_bindings(numbered),
        *(
            _original_table_binding(pair, numbered.recognized_pages)
            for pair in numbered.reprints
        ),
    ]
    declaration_pages, nonfinal_declaration_ids = observe_declaration_pages(
        doc,
        processed_structures,
        candidate_pages,
        pages_text,
        tokens_for_page,
        grids_for_page=grids_for_page,
        progress=progress,
    )
    candidates = [_candidate(binding, "numbered_cell") for binding in table_bindings]
    caption_owned = {str(pair["structure"]["id"]) for pair in caption_grids.bindings}
    remaining = [
        structure
        for structure in processed_structures
        if str(structure["id"]) in caption_owned
        or (
            int(structure["page_no"]) - 1 not in reserved_pages
            and str(structure["id"]) not in numbered.protected_structure_ids
        )
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
        withheld_structure_ids=frozenset(nonfinal_declaration_ids),
        grids_for_page=grids_for_page,
        tokens_for_page=tokens_for_page,
        grid_result=caption_grids,
        progress=progress,
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
    claims = resolve_source_claims(candidates)
    accepted, conflicts = claims.primary, claims.conflicts
    reprints = []
    for candidate in claims.reprints:
        binding = dict(candidate.binding)
        reprints.append(
            annotate_source_binding(
                _normalise_binding_to_compound(binding, candidate.label_key)
            )
        )
    conflicts = (
        *conflicts,
        *(
            BindingConflict(
                issue["cpd"],
                issue["page_no"] - 1,
                issue["reason"],
                {
                    **issue.get("evidence", {}),
                    **(
                        {"structure_id": issue["structure_id"]}
                        if issue.get("structure_id")
                        else {}
                    ),
                },
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
