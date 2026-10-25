"""Exact original headings and independently observed crop labels, no ID repair."""

from __future__ import annotations

from .activity_identity import normalize_compound
from .binding_candidates import _build_binding_from_structure
from .binding_observations import (
    _annotate_bindings_with_visible_labels,
    _load_visible_label_cache,
    _refine_visible_label_cache_with_page_ocr,
)
from .binding_progress import observed_items
from .binding_source_regions import (
    identifier_references,
    reference_cell,
    reference_regions,
)
from .caption_label_roles import caption_label_index, caption_label_reference
from .caption_locator_source import observe_caption_locator
from .caption_pending_roles import pending_caption_index, pending_caption_reference
from .heading_declaration_index import HeadingDeclarationIndex
from .heading_evidence import (
    heading_structure_evidence,
    original_heading_lines,
)
from .heading_group_scope import group_heading_members, observe_group_context
from .heading_line_windows import heading_line_windows
from .heading_observation import observe_heading
from .heading_source_proof import proved_heading_declaration
from .pipeline_rules import annotate_binding_accuracy
from .plot_legend_locator import legend_candidate
from .plot_reference import observe_plot_reference
from .source_document import document_sha256 as _document_sha256
from .source_evidence_identity import proof_id
from .source_geometry import source_layout
from .source_section_roles import (
    heading_list_hint,
    heading_members,
    section_heading,
)
from .structure_declaration_roles import (
    declaration_label_reference,
    declaration_role_index,
)


def observed_heading_blocks(
    doc,
    pages: list[int],
    line_map: dict,
    *,
    source_sections: list[dict] | None = None,
    source_line_map: dict | None = None,
    source_regions: dict | None = None,
    grids_for_page=None,
    tokens_for_page=None,
    source_bindings=(),
    source_diagnostics=None,
    progress=None,
) -> list[dict]:
    """Coordinates and complete labels originate in the source, not an ID list."""
    blocks = []
    document_sha256 = _document_sha256(doc)
    caption_labels = caption_label_index(source_bindings, document_sha256)
    pending_captions = pending_caption_index(source_diagnostics or {}, document_sha256)
    declaration_roles = declaration_role_index(source_sections or [], document_sha256)
    for page_index in observed_items("heading_sources", sorted(set(pages)), progress):
        page = doc[page_index]
        plot_cache = {}
        group_context = None
        layout = source_layout(page)
        regions = (source_regions or {}).get(page_index)
        if regions is None:
            grids = grids_for_page(page) if grids_for_page else None
            tokens = (
                tokens_for_page(page)
                if tokens_for_page and (grids is None or grids)
                else None
            )
            regions = reference_regions(
                page, original_pdf_sha256=document_sha256, grids=grids, tokens=tokens
            )
        if source_sections is not None and source_regions is None:
            source_sections.extend(
                {
                    "role": "characterization_region",
                    "page_no": page_index + 1,
                    "source_region": region,
                }
                for region in regions
            )
            source_sections.extend(
                reference
                for region in regions
                for reference in identifier_references(region)
            )
        observed = original_heading_lines(
            doc[page_index],
            line_map.get(page_index, []),
            (source_line_map or {}).get(page_index, []),
        )
        for line in heading_line_windows(observed):
            observation = section_heading(line["text"])
            graphical = None
            legend = legend_candidate(line["text"]) if observation is None else None
            if legend is not None:
                graphical = observe_plot_reference(
                    page,
                    line,
                    observed,
                    document_sha256,
                    cache=plot_cache,
                    tokens_for_page=tokens_for_page,
                )
                if graphical is not None:
                    observation = section_heading(graphical["nomination"]["text"])
                else:
                    # A refused graphic observation cannot erase its nominated
                    # printed-ID occurrence. This is a candidate only: the same
                    # original heading proof must still qualify it below, or it
                    # remains an explicit unproved source, never a product.
                    observation = section_heading(legend[2])
            if observation is None and (
                heading_list_hint(line["text"]) or line.get("unresolved_role_prefix")
            ):
                observation = {
                    "role": "unproved_heading",
                    "identifier": "",
                    "identifiers": [],
                    "line_text": line["text"],
                }
            if observation:
                declaration_reference = declaration_label_reference(
                    line, page_index + 1, declaration_roles
                )
                if declaration_reference is not None:
                    if source_sections is not None:
                        source_sections.append(declaration_reference)
                    continue
                label_reference = caption_label_reference(
                    line, page_index + 1, caption_labels
                )
                if label_reference is None:
                    label_reference = observe_caption_locator(
                        page,
                        line,
                        caption_labels,
                        grids_for_page=grids_for_page,
                    )
                if label_reference is not None:
                    if source_sections is not None:
                        source_sections.append(label_reference)
                    continue
                pending_reference = pending_caption_reference(
                    line, page_index + 1, pending_captions, document_sha256
                )
                if pending_reference is not None:
                    if source_sections is not None:
                        source_sections.append(pending_reference)
                    continue
                reference = reference_cell(line, regions)
                if reference is not None:
                    if source_sections is not None:
                        source_sections.append(
                            {
                                **observation,
                                "role": "characterization_reference",
                                "page_no": page_index + 1,
                                "bbox": line["bbox"],
                                "line_source": line["source"],
                                "geometry_space": line["geometry_space"],
                                **reference,
                            }
                        )
                    continue
                proof = graphical
                if legend is None:
                    proof = observe_plot_reference(
                        page,
                        line,
                        observed,
                        document_sha256,
                        cache=plot_cache,
                        tokens_for_page=tokens_for_page,
                    )
                if proof is None:
                    proof = observe_heading(
                        page,
                        line,
                        document_sha256,
                        layout=layout,
                        grids=grids_for_page(page) if grids_for_page else None,
                    )
                declared = proved_heading_declaration(proof)
                effective = declared or observation
                section = {
                    **effective,
                    "page_no": page_index + 1,
                    "bbox": proof["nomination"]["bbox"],
                    "heading_observation": proof,
                    "status": proof["status"],
                    "role": effective["role"] if declared else "unproved_heading",
                }
                if (
                    declared
                    and declared["role"] == "compound_heading"
                    and len(heading_members(declared)) > 1
                    and tokens_for_page
                ):
                    if group_context is None:
                        group_context = observe_group_context(
                            page, tokens_for_page(page), document_sha256
                        )
                    section["group_context"] = group_context
                covered_members = group_heading_members(
                    section, source_bindings, document_sha256
                )
                if source_sections is not None:
                    source_sections.append(section)
                if declared and declared["role"] in {
                    "assay_section",
                    "intermediate_section",
                    "figure_label_reference",
                }:
                    continue
                for identifier in heading_members(effective):
                    if identifier in covered_members:
                        continue
                    blocks.append(
                        {
                            "cpd": f"Compound {identifier}",
                            "page_no": page_index + 1,
                            "y0": line["y0"],
                            "y1": line["y1"],
                            "bbox": line["bbox"],
                            "line_text": effective["line_text"],
                            "heading_observation": proof,
                        }
                    )
    return sorted(blocks, key=lambda block: (block["page_no"], block["y0"]))


def select_heading_bindings(
    doc,
    structures: list[dict],
    blocks: list[dict],
    line_map: dict,
    output_dir: str,
    profile: dict,
    *,
    source_line_map: dict | None = None,
    all_structures: list[dict] | None = None,
    source_sections: list[dict] | None = None,
    source_cells=(),
    grids_for_page=None,
    progress=None,
) -> tuple[list[dict], list[dict]]:
    """Require mutually unique crop/printed-label proof in an observed interval."""
    if (not structures and all_structures is None) or not blocks:
        return [], [
            {"cpd": b["cpd"], "page_no": b["page_no"], "reason": "no_heading_structure"}
            for b in blocks
        ]
    document_sha256 = _document_sha256(doc)
    proved_blocks = []
    for block in blocks:
        proof = block.get("heading_observation")
        declaration = proved_heading_declaration(proof)
        if (
            declaration
            and declaration["role"] == "compound_heading"
            and proof["original_pdf_sha256"] == document_sha256
            and proof["page_no"] == block["page_no"]
            and proof["nomination"]["bbox"] == block["bbox"]
        ):
            proved_blocks.append((block, declaration))
    if not proved_blocks:
        return [], [
            {
                "cpd": block["cpd"],
                "page_no": block["page_no"],
                "reason": "ambiguous_or_unproved_original_heading",
            }
            for block in blocks
        ]
    inventory = all_structures if all_structures is not None else structures
    if any(
        s.get("source_pdf_sha256", document_sha256) != document_sha256
        for s in inventory
    ):
        return [], [
            {
                "cpd": b["cpd"],
                "page_no": b["page_no"],
                "reason": "foreign_original_heading_structure",
            }
            for b in blocks
        ]
    structures = [
        {**structure, "source_pdf_sha256": document_sha256} for structure in structures
    ]
    structure_index = {str(s["id"]): s for s in structures}
    pending = observed_items("heading_bindings", proved_blocks, progress)
    cache = _load_visible_label_cache(output_dir, profile)
    cache = _refine_visible_label_cache_with_page_ocr(
        structures, cache, line_map, output_dir, profile
    )
    candidates = {}
    index = HeadingDeclarationIndex(
        doc,
        inventory,
        lambda number: original_heading_lines(
            doc[number - 1],
            line_map.get(number - 1, []),
            (source_line_map or {}).get(number - 1, []),
        ),
        document_sha256,
        source_sections=source_sections or (),
        source_cells=source_cells,
        grids_for_page=grids_for_page,
    )
    scopes = {}
    for block, _ in pending:
        key = normalize_compound(block["cpd"]).removeprefix("Compound ")
        heading = block["heading_observation"]
        identity = proof_id(heading)
        if identity not in scopes:
            scopes[identity] = index.observe(heading)
        scope = scopes[identity]
        block = {**block, "declaration_scope": scope}
        direct, evidence = heading_structure_evidence(
            block,
            structure_index,
            scope,
            document=doc,
        )
        if direct and evidence:
            binding = _build_binding_from_structure(direct, key)
            binding.update(
                {
                    "binding_rule": "original_heading_reaction_product"
                    if evidence["reaction_source"] is not None
                    else "original_heading_standalone",
                    "original_heading_evidence": dict(block),
                    "original_heading_structure_evidence": evidence,
                    "source_pdf_sha256": document_sha256,
                }
            )
            binding = _annotate_bindings_with_visible_labels([binding], cache)[0]
            checked = annotate_binding_accuracy(binding)
            if checked.get("accuracy_status") == "confirmed" and not checked.get(
                "fail_closed"
            ):
                candidates.setdefault(key, {})[str(checked["structure_id"])] = checked
    for section in source_sections or ():
        heading = section.get("heading_observation")
        if isinstance(heading, dict) and proof_id(heading) in scopes:
            section["declaration_scope"] = scopes[proof_id(heading)]
    owners = {}
    for label, images in candidates.items():
        for image in images:
            owners.setdefault(image, set()).add(label)
    bindings, issues, seen = [], [], set()
    for block in blocks:
        label = normalize_compound(block["cpd"]).removeprefix("Compound ")
        if label in seen:
            continue
        seen.add(label)
        matching = candidates.get(label, {})
        if len(matching) == 1 and len(owners[next(iter(matching))]) == 1:
            bindings.append(next(iter(matching.values())))
        else:
            issues.append(
                {
                    "cpd": block["cpd"],
                    "page_no": block["page_no"],
                    "reason": "ambiguous_or_unproved_original_heading",
                }
            )
    return bindings, issues
