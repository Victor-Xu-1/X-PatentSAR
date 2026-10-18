"""Source-led binding coordinator: one original ownership path and one writer."""

from __future__ import annotations

import fitz

from .binding_artifacts import write_binding_result
from .binding_geometry import _process_structure
from .binding_preparation import load_binding_input, prepare_binding_observations
from .binding_progress import BindingObserver
from .binding_source_headings import (
    _document_sha256,
    observed_heading_blocks,
    select_heading_bindings,
)
from .binding_source_regions import collect_reference_regions
from .binding_spatial import collect_spatial_bindings
from .source_role_observations import RoleObservationBuffer


def bind(
    pdf_path: str,
    profile: dict,
    output_dir: str,
    structures_path: str | None = None,
    include_intermediates: bool = False,
    cpd_prefix_pattern: str | None = None,
    progress: BindingObserver | None = None,
) -> dict:
    """Prove printed IDs independently of activities; ambiguous sources stay withheld."""
    del cpd_prefix_pattern
    out, structures, patent_id = load_binding_input(output_dir, structures_path)
    with fitz.open(pdf_path) as doc:
        observations = prepare_binding_observations(
            doc, pdf_path, profile, out, structures
        )
        processed = [_process_structure(structure) for structure in structures]
        spatial = collect_spatial_bindings(
            doc,
            processed,
            observations.pages_text,
            observations.line_map,
            [],
            {key: value for key, value in profile.items() if key != "active_cpds"},
            observations.authoritative_table_pages,
            source_pages=observations.page_indices,
            progress=progress,
        )
        document_sha256 = _document_sha256(doc)
        original = [
            {**binding, "source_pdf_sha256": document_sha256}
            for binding in spatial.catalogue()
        ]
        reprints = [
            {**binding, "source_pdf_sha256": document_sha256}
            for binding in spatial.reprints
        ]
        generic = spatial.structures(processed)
        source_sections = list(spatial.source_sections)
        role_observations = RoleObservationBuffer()
        source_regions = collect_reference_regions(
            doc,
            range(len(doc)),
            source_sections,
            original_pdf_sha256=document_sha256,
            grids_for_page=spatial.grids_for_page,
            tokens_for_page=spatial.tokens_for_page,
            role_observations=role_observations,
            progress=progress,
        )
        # A known catalogue owns its cells, not every other heading on that page.
        pages = list(range(len(doc)))
        blocks = (
            observed_heading_blocks(
                doc,
                pages,
                observations.line_map,
                source_sections=source_sections,
                source_line_map=observations.source_line_map,
                source_regions=source_regions,
                grids_for_page=spatial.grids_for_page,
                tokens_for_page=spatial.tokens_for_page,
                source_bindings=[*original, *reprints],
                progress=progress,
            )
            if pages
            else []
        )
        heading_bindings, heading_issues = (
            select_heading_bindings(
                doc,
                generic,
                blocks,
                observations.line_map,
                output_dir,
                profile,
                source_line_map=observations.source_line_map,
                progress=progress,
            )
            if blocks
            else ([], [])
        )
        issues = [
            {
                "cpd": conflict.label_key,
                "page_no": conflict.page_index + 1,
                "reason": conflict.reason,
                "evidence": conflict.evidence,
            }
            for conflict in spatial.conflicts
        ]
        issues.extend(heading_issues)
        return write_binding_result(
            out,
            patent_id=patent_id,
            bindings=[],
            catalog_bindings=[*original, *heading_bindings],
            catalog_sources=reprints,
            source_issues=issues,
            source_sections=source_sections,
            role_observations=role_observations,
            original_pdf_sha256=document_sha256,
            detected_style="original_cell_caption_heading",
            include_intermediates=include_intermediates,
            total_structures=len(structures),
            total_compound_blocks=len(blocks),
            table_pages=spatial.recognized_table_pages,
            table_covered_count=len(original),
            no_binding=[issue.get("cpd", "") for issue in issues],
            unbound_pages=issues,
        )
