"""Source-led binding coordinator: one original ownership path and one writer."""

from __future__ import annotations

from .binding_artifacts import write_binding_result
from .binding_geometry import _process_structure
from .binding_labels import _cpd_label_key
from .binding_ocr import PYMUPDF_AVAILABLE, fitz
from .binding_preparation import load_binding_input, prepare_binding_observations
from .binding_source_headings import observed_heading_blocks, select_heading_bindings
from .binding_spatial import collect_spatial_bindings


def bind(
    pdf_path: str,
    profile: dict,
    output_dir: str,
    structures_path: str | None = None,
    include_intermediates: bool = False,
    cpd_prefix_pattern: str | None = None,
) -> dict:
    """Prove printed IDs independently of activities; ambiguous sources stay withheld."""
    del cpd_prefix_pattern
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF is required for original-PDF binding")
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
        )
        original = spatial.catalogue()
        generic = spatial.structures(processed)
        pages = [
            page
            for page in observations.page_indices
            if page not in spatial.ownership.page_indices
        ]
        blocks = (
            observed_heading_blocks(doc, pages, observations.line_map)
            if generic
            else []
        )
        blocks = [
            block
            for block in blocks
            if _cpd_label_key(block["cpd"]) not in spatial.ownership.label_keys
        ]
        heading_bindings, heading_issues = (
            select_heading_bindings(
                doc, generic, blocks, observations.line_map, output_dir, profile
            )
            if generic and blocks
            else ([], [])
        )
        heading_bindings = [
            binding
            for binding in heading_bindings
            if not spatial.ownership.protects(
                _cpd_label_key(binding["cpd"]),
                str(binding["structure_id"]),
                int(binding["page_no"]) - 1,
            )
        ]
        issues = [
            {
                "cpd": conflict.label_key,
                "page_no": conflict.page_index + 1,
                "reason": conflict.reason,
            }
            for conflict in spatial.conflicts
        ]
        issues.extend(heading_issues)
        return write_binding_result(
            out,
            patent_id=patent_id,
            bindings=[],
            catalog_bindings=[*original, *heading_bindings],
            catalog_sources=spatial.reprints,
            source_issues=issues,
            detected_style="original_cell_caption_heading",
            include_intermediates=include_intermediates,
            total_structures=len(structures),
            total_compound_blocks=len(blocks),
            table_pages=observations.authoritative_table_pages,
            table_covered_count=len(original),
            no_binding=[issue.get("cpd", "") for issue in issues],
            unbound_pages=issues,
        )
