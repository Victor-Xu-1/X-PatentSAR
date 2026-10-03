"""Activity-led binding coordinator: one source-ownership path and one writer."""

from __future__ import annotations

import logging

from .binding_arbitration import finalize_binding_candidates
from .binding_artifacts import write_binding_result
from .binding_geometry import _process_structure
from .binding_headings import find_binding_blocks
from .binding_labels import _cpd_label_key
from .binding_ocr import PYMUPDF_AVAILABLE, fitz
from .binding_preparation import load_binding_input, prepare_binding_observations
from .binding_recovery import recover_generic_bindings
from .binding_selection import select_generic_bindings
from .binding_spatial import (
    _enforce_authoritative_structure_table_source,
    collect_spatial_bindings,
)
from .binding_types import BinderConfig, BindingSelection

logger = logging.getLogger(__name__)


def bind(
    pdf_path: str,
    profile: dict,
    output_dir: str,
    structures_path: str | None = None,
    include_intermediates: bool = False,
    cpd_prefix_pattern: str | None = None,
) -> dict:
    """Bind original segmented structures in authoritative activity order.

    The public arguments and output shape remain unchanged. The legacy prefix
    argument stays in the signature; observed source ownership is authoritative.
    Generic strategies see only unclaimed labels/segments/pages. Withheld cells
    remain withheld and strict downstream acceptance still owns final delivery.
    """
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required for original-PDF binding")
    out, structures, patent_id = load_binding_input(output_dir, structures_path)
    active_cpds = profile.get("active_cpds", []) or []
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
            active_cpds,
            profile,
            observations.authoritative_table_pages,
        )
        if spatial.complete(active_cpds):
            # Complete original cells/captions bypass heading, crop OCR and all
            # generic recovery. Context-manager exit also closes on exceptions.
            final_bindings = spatial.ordered(active_cpds)
            selection = BindingSelection(
                final_bindings,
                [],
                "original_cell_and_caption",
                [],
                [],
                {},
                [],
            )
            logger.info(
                "Complete original spatial coverage: %d compounds", len(final_bindings)
            )
        else:
            generic_structures = spatial.structures(processed)
            generic_active = [
                cpd
                for cpd in active_cpds
                if _cpd_label_key(cpd) not in spatial.ownership.label_keys
            ]
            pages_text = {
                page: text
                for page, text in observations.pages_text.items()
                if page not in spatial.ownership.page_indices
            }
            line_map = {
                page: lines
                for page, lines in observations.line_map.items()
                if page not in spatial.ownership.page_indices
            }
            if generic_structures and generic_active:
                blocks, style = find_binding_blocks(
                    doc,
                    pages_text,
                    line_map,
                    [
                        page
                        for page in observations.page_indices
                        if page not in spatial.ownership.page_indices
                    ],
                    observations.workers,
                )
                blocks = [
                    block
                    for block in blocks
                    if _cpd_label_key(str(block.get("cpd") or ""))
                    not in spatial.ownership.label_keys
                ]
                generic_profile = {**profile, "active_cpds": generic_active}
                selection = select_generic_bindings(
                    doc,
                    generic_structures,
                    pages_text,
                    line_map,
                    generic_active,
                    blocks,
                    style,
                    output_dir,
                    generic_profile,
                    observations.workers,
                    include_intermediates,
                    BinderConfig(),
                )
                generic = recover_generic_bindings(
                    doc,
                    selection,
                    generic_structures,
                    pages_text,
                    line_map,
                    generic_active,
                    out,
                    output_dir,
                )
            else:
                # An observed but ambiguous source is not a missing generic
                # input. No alternate sequence or fabricated evidence fills it.
                selection = BindingSelection(
                    [],
                    [],
                    "original_cell_and_caption",
                    list(generic_active),
                    [],
                    {},
                    [],
                )
                generic = []
            generic = _enforce_authoritative_structure_table_source(generic, profile)
            final_bindings = spatial.restore(generic, active_cpds)
            final_bindings = finalize_binding_candidates(
                final_bindings,
                active_cpds,
                profile,
                selection.visible_label_cache,
                line_map,
            )
        return write_binding_result(
            out,
            patent_id=patent_id,
            bindings=final_bindings,
            detected_style=selection.detected_style,
            include_intermediates=include_intermediates,
            total_structures=len(structures),
            total_compound_blocks=len(selection.blocks),
            table_pages=profile.get("authoritative_structure_table_pages", []) or [],
            table_covered_count=len(
                profile.get("authoritative_structure_table_cpds", []) or []
            ),
            no_binding=selection.no_binding,
            unbound_pages=selection.unbound_pages,
            catalog_bindings=[*spatial.catalogue(), *final_bindings],
            catalog_sources=spatial.reprints,
        )
