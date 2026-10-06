"""Original numbered-cell and exact-caption source authority."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType
from typing import (
    Any,
)

from patent_sar_extractor.core.numbered_structure_binding import (
    NumberedTableResult,
    bind_numbered_tables,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.series_table_binding import (
    SeriesTableResult,
    pair_series_table,
)
from patent_sar_extractor.core.visible_structure_binding import bind_visible_captions

from .binding_candidates import (
    _active_ordered_bindings,
    _build_binding_from_structure,
    _normalise_binding_to_compound,
)
from .binding_geometry import (
    _group_structures_by_row,
)
from .binding_labels import (
    _active_label_keys,
    _binding_label_key,
)
from .binding_observations import (
    _normalise_ocr_line_map,
)
from .binding_types import (
    BindingCandidate,
    BindingConflict,
    SourceKind,
    SourceOwnership,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpatialBindings:
    candidates: tuple[BindingCandidate, ...]
    ownership: SourceOwnership
    conflicts: tuple[BindingConflict, ...]
    numbered_recognized: bool
    reprints: tuple[dict[str, Any], ...] = ()
    recognized_table_pages: frozenset[int] = frozenset()

    def ordered(self, active_cpds: list[str]) -> list[dict[str, Any]]:
        if not active_cpds:
            return []
        return [
            annotate_binding_accuracy(binding)
            for binding in _active_ordered_bindings(
                [dict(candidate.binding) for candidate in self.candidates], active_cpds
            )
        ]

    def catalogue(self) -> list[dict[str, Any]]:
        """Primary source ownership is printed-ID based, never activity-filtered."""
        return [
            annotate_binding_accuracy(
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
            for page in (*table_pages, *source_pages)
            if type(page) is int and page >= 0
        }
    )
    numbered = bind_numbered_tables(doc, processed_structures, candidate_pages, None)
    series = (
        pair_series_table(
            processed_structures,
            candidate_pages,
            _normalise_ocr_line_map(line_map),
            None,
        )
        if not numbered.recognized
        else SeriesTableResult(0, ())
    )
    recognized_pages = set(numbered.recognized_pages) | set(series.recognized_pages)
    observed_keys = set(numbered.observed_keys) | (
        set(series.observed_keys) if series.recognized else set()
    )
    table_bindings = _extract_authoritative_structure_table_sequence_bindings(
        processed_structures,
        pages_text,
        active_cpds,
        profile,
        ocr_line_map=line_map,
        numbered_result=numbered,
        series_result=series,
    )
    candidates = [
        _candidate(binding, "numbered_cell" if numbered.recognized else "legacy_table")
        for binding in table_bindings
    ]
    remaining = [
        structure
        for structure in processed_structures
        if int(structure["page_no"]) - 1 not in recognized_pages
    ]
    captions = bind_visible_captions(doc, remaining, None, excluded=observed_keys)
    caption_ids = set()
    caption_keys = set()
    for pair in captions:
        binding = _build_binding_from_structure(pair.structure, pair.label)
        binding.update(
            {
                "binding_rule": "direct_structure_label",
                "visible_label": pair.label,
                "visible_label_candidates": [
                    {"label": pair.label, "source": "pdf_clip"}
                ],
                "visible_label_crop_source": "pdf_clip",
                "product_context_nearby": True,
                "product_context_distance": 0,
                "exact_caption_evidence": {
                    "bbox": list(pair.label_bbox),
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
        binding = _build_binding_from_structure(pair.structure, pair.label)
        binding.update(
            {
                "binding_rule": "numbered_structure_table_cell",
                "numbered_table_cell_evidence": pair.evidence(),
                "authoritative_table_source_label": pair.label,
                "authoritative_table_pages": list(numbered.recognized_pages),
            }
        )
        reprints.append(
            annotate_binding_accuracy(
                _normalise_binding_to_compound(binding, pair.label)
            )
        )
    conflicts = (
        *conflicts,
        *(
            BindingConflict(issue.label, issue.page_index, issue.reason)
            for issue in numbered.issues
        ),
    )
    ownership = SourceOwnership(
        page_indices=frozenset(recognized_pages),
        structure_ids=frozenset(
            caption_ids
            | {candidate.structure_id for candidate in candidates}
            | {str(binding["structure_id"]) for binding in reprints}
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
        frozenset(recognized_pages),
    )


def _enforce_authoritative_structure_table_source(
    final_bindings: list[dict], profile: dict | None
) -> list[dict]:
    """Reject synthesis-page competitors for compound IDs present in a structure table."""
    raw_pages = (profile or {}).get("authoritative_structure_table_pages", []) or []
    raw_cpds = (profile or {}).get("authoritative_structure_table_cpds", []) or []
    table_page_nos = set()
    for page_idx in raw_pages:
        try:
            table_page_nos.add(int(page_idx) + 1)
        except (TypeError, ValueError, OverflowError) as exc:
            logger.debug("Invalid authoritative table page: %s", type(exc).__name__)
            continue
    covered_keys = _active_label_keys([str(cpd) for cpd in raw_cpds])
    if not table_page_nos or not covered_keys:
        return final_bindings
    active_keys = _active_label_keys((profile or {}).get("active_cpds", []) or [])
    if active_keys and not active_keys.issubset(covered_keys):
        # A partial structure table is useful evidence, but it is not a global
        # authority. Do not delete clear visual bindings for active compounds
        # merely because one incomplete table mentions the same number.
        return final_bindings

    kept: list[dict] = []
    dropped: list[str] = []
    for binding in final_bindings:
        key = _binding_label_key(binding)
        try:
            page_no = int(binding.get("page_no") or 0)
        except (TypeError, ValueError, OverflowError):
            page_no = 0
        if key in covered_keys and page_no not in table_page_nos:
            dropped.append(key)
            continue
        kept.append(binding)
    if dropped:
        logger.info(
            "   结构表权威来源保护: 删除 %d 个表外竞争绑定 (%s)",
            len(dropped),
            ", ".join(sorted(set(dropped), key=lambda value: (len(value), value))[:12]),
        )
    return kept


def _extract_authoritative_structure_table_sequence_bindings(
    processed_structures: list[dict],
    pages_text: dict[int, str],
    active_cpds: list[str],
    profile: dict | None,
    ocr_line_map: dict[int, list[Any]] | None = None,
    *,
    numbered_result: NumberedTableResult | None = None,
    series_result: SeriesTableResult | None = None,
) -> list[dict]:
    """Resolve authoritative cells before series or legacy sequence evidence.

    Recognized numbered grids never enter global sequence inference. Existing
    I-series geometry remains independent; the older complete-sequence rule is
    restricted to tables not recognized by either spatial authority.
    """
    if numbered_result is not None and numbered_result.recognized:
        bindings = []
        for pair in numbered_result.bindings:
            binding = _build_binding_from_structure(pair.structure, pair.label)
            binding["binding_rule"] = "numbered_structure_table_cell"
            binding["numbered_table_cell_evidence"] = pair.evidence()
            binding["authoritative_table_source_label"] = pair.label
            binding["authoritative_table_pages"] = list(
                numbered_result.recognized_pages
            )
            bindings.append(binding)
        if numbered_result.issues:
            logger.warning(
                "   编号结构表保留未确认单元格: %d (%s)",
                len(numbered_result.issues),
                ", ".join(sorted({issue.reason for issue in numbered_result.issues})),
            )
        # Recognition is authoritative even when every cell is unresolved.
        # A numeric global zip cannot resolve missing/ambiguous cell evidence.
        return bindings

    raw_pages = (
        series_result.recognized_pages
        if series_result is not None and series_result.recognized
        else (profile or {}).get("authoritative_structure_table_pages", []) or []
    )
    try:
        page_indices = sorted({int(page) for page in raw_pages})
    except (TypeError, ValueError, OverflowError):
        return []
    if not page_indices or page_indices[0] < 0:
        return []

    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    active_keys = _active_label_keys(active_cpds)
    series = (
        series_result
        if series_result is not None
        else pair_series_table(
            processed_structures, page_indices, lines_by_page, active_keys
        )
    )
    if series.rejected_geometry or series.ambiguous_pairings:
        logger.warning(
            "   权威 I-NNN 表拒绝无效坐标=%d, 歧义配对=%d",
            series.rejected_geometry,
            series.ambiguous_pairings,
        )
    if series.recognized:
        bindings: list[dict] = []
        for pair in series.bindings:
            binding = _build_binding_from_structure(pair.structure, str(pair.label))
            binding["binding_rule"] = "authoritative_structure_table_sequence"
            binding["authoritative_table_sequence_confirmed"] = True
            binding["authoritative_table_sequence_position"] = (
                pair.evidence_position + 1
            )
            binding["authoritative_table_label_count"] = series.label_count
            binding["authoritative_table_structure_count"] = len(processed_structures)
            binding["authoritative_table_pages"] = page_indices
            binding["authoritative_table_visible_label"] = f"I-{pair.label}"
            binding["authoritative_table_label_y0"] = round(pair.label_y, 2)
            binding["authoritative_table_pair_distance"] = round(
                pair.center_distance, 2
            )
            binding["authoritative_table_source_label"] = f"I-{pair.source_label}"
            if pair.correction_reason:
                binding["authoritative_table_label_corrected"] = True
                binding["authoritative_table_label_correction_reason"] = (
                    pair.correction_reason
                )
            bindings.append(binding)
        logger.info(
            "   权威 I-NNN 结构表坐标绑定: %d active rows, labels=%d, structures=%d",
            len(bindings),
            series.label_count,
            len(processed_structures),
        )
        # A recognized but ambiguous series table must not enter the numeric
        # global-sequence rule, which cannot resolve its spatial uncertainty.
        return bindings

    # The source-led coordinator never enters the legacy sequence adapter.
    # Retained callers must explicitly supply their old activity-filter scope.
    if not active_keys:
        return []

    # Only the numeric global zip requires a complete contiguous table. The
    # I-series rule above pairs within each observed original-PDF page.
    if any(b != a + 1 for a, b in pairwise(page_indices)):
        return []
    label_re = re.compile(
        r"(?:Compound|Cpd|化合物|实施例)\s*[-:]?\s*([1-9]\d{0,3})(?![\dA-Za-z-])",
        re.IGNORECASE,
    )
    labels = {
        int(match.group(1))
        for page_idx in page_indices
        for match in label_re.finditer(str(pages_text.get(page_idx, "") or ""))
    }
    if len(labels) < 6:
        return []
    ordered_labels = sorted(labels)
    if ordered_labels != list(range(ordered_labels[0], ordered_labels[-1] + 1)):
        return []

    table_structures: list[dict] = []
    for page_idx in page_indices:
        page_structs = [
            struct
            for struct in processed_structures
            if int(struct.get("page_no") or 0) == page_idx + 1
        ]
        rows = _group_structures_by_row(page_structs, y_threshold=42.0)
        table_structures.extend(
            struct
            for row in rows
            for struct in sorted(row, key=lambda item: float(item.get("x0") or 0))
        )
    if len(table_structures) != len(ordered_labels):
        logger.warning(
            "   权威结构表全局序列未启用: labels=%d, structures=%d",
            len(ordered_labels),
            len(table_structures),
        )
        return []

    bindings: list[dict] = []
    for position, (compound_num, struct) in enumerate(
        zip(ordered_labels, table_structures), start=1
    ):
        key = str(compound_num)
        if key not in active_keys:
            continue
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = "authoritative_structure_table_sequence"
        binding["authoritative_table_sequence_confirmed"] = True
        binding["authoritative_table_sequence_position"] = position
        binding["authoritative_table_label_count"] = len(ordered_labels)
        binding["authoritative_table_structure_count"] = len(table_structures)
        binding["authoritative_table_pages"] = page_indices
        bindings.append(binding)
    if bindings:
        logger.info(
            "   📋 权威结构表跨页全局顺序绑定: %d/%d active rows, pages=%s",
            len(bindings),
            len(ordered_labels),
            page_indices,
        )
    return bindings
