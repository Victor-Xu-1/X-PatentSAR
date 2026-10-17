"""Exact original headings and independently observed crop labels, no ID repair."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .activity_identity import normalize_compound
from .binding_candidates import _build_binding_from_structure
from .binding_observations import (
    _annotate_bindings_with_visible_labels,
    _load_visible_label_cache,
    _refine_visible_label_cache_with_page_ocr,
)
from .binding_source_regions import (
    identifier_references,
    reference_cell,
    reference_regions,
)
from .caption_label_roles import caption_label_index, caption_label_reference
from .heading_evidence import (
    original_heading_lines,
    standalone_heading_evidence,
)
from .heading_line_windows import heading_line_windows
from .heading_observation import observe_heading
from .heading_source_proof import proved_heading_declaration
from .pipeline_rules import _candidate_labels, annotate_binding_accuracy
from .source_geometry import source_layout
from .source_section_roles import heading_list_hint, heading_members, section_heading


def _document_sha256(doc) -> str:
    """Label observations can include pixels outside the molecule crop."""
    if doc.name and not doc.is_dirty:
        with Path(doc.name).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    return hashlib.sha256(doc.tobytes(no_new_id=True)).hexdigest()


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
) -> list[dict]:
    """Coordinates and complete labels originate in the source, not an ID list."""
    blocks = []
    document_sha256 = _document_sha256(doc)
    caption_labels = caption_label_index(source_bindings, document_sha256)
    for page_index in sorted(set(pages)):
        page = doc[page_index]
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
            if observation is None and heading_list_hint(line["text"]):
                observation = {
                    "role": "unproved_heading",
                    "identifier": "",
                    "identifiers": [],
                    "line_text": line["text"],
                }
            if observation:
                label_reference = caption_label_reference(
                    line, page_index + 1, caption_labels
                )
                if label_reference is not None:
                    if source_sections is not None:
                        source_sections.append(label_reference)
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
                proof = observe_heading(page, line, document_sha256, layout=layout)
                declared = proved_heading_declaration(proof)
                effective = declared or observation
                if source_sections is not None:
                    source_sections.append(
                        {
                            **effective,
                            "page_no": page_index + 1,
                            "bbox": line["bbox"],
                            "heading_observation": proof,
                            "status": proof["status"],
                            "role": effective["role"]
                            if declared
                            else "unproved_heading",
                        }
                    )
                if declared and declared["role"] in {
                    "assay_section",
                    "intermediate_section",
                }:
                    continue
                for identifier in heading_members(effective):
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
) -> tuple[list[dict], list[dict]]:
    """Require mutually unique crop/printed-label proof in an observed interval."""
    if not structures or not blocks:
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
    first_heading = {}
    for block, _ in proved_blocks:
        page_no = block["page_no"]
        first_heading[page_no] = min(
            first_heading.get(page_no, block["y0"]), block["y0"]
        )
    structures = [
        {**structure, "source_pdf_sha256": document_sha256}
        for structure in structures
        if structure["page_no"] in first_heading
        and structure["y0"] >= first_heading[structure["page_no"]]
    ]
    page_structures = {}
    for structure in structures:
        page_structures.setdefault(structure["page_no"], []).append(structure)
    cache = _load_visible_label_cache(output_dir, profile)
    cache = _refine_visible_label_cache_with_page_ocr(
        structures, cache, line_map, output_dir, profile
    )
    candidates = {}
    boundaries = sorted({(block["page_no"], block["y0"]) for block in blocks})
    ends = {
        (page_no, y): (
            boundaries[index + 1][1]
            if index + 1 < len(boundaries) and boundaries[index + 1][0] == page_no
            else doc[page_no - 1].rect.height
        )
        for index, (page_no, y) in enumerate(boundaries)
    }
    original_lines = {}
    for block, declaration in proved_blocks:
        key = normalize_compound(block["cpd"]).removeprefix("Compound ")
        end = ends[block["page_no"], block["y0"]]
        page = doc[block["page_no"] - 1]
        if block["page_no"] not in original_lines:
            original_lines[block["page_no"]] = original_heading_lines(
                page,
                line_map.get(block["page_no"] - 1, []),
                (source_line_map or {}).get(block["page_no"] - 1, []),
            )
        direct, evidence = standalone_heading_evidence(
            page,
            block,
            page_structures.get(block["page_no"], []),
            original_lines[block["page_no"]],
            end,
        )
        if direct and evidence:
            binding = _build_binding_from_structure(direct, key)
            binding.update(
                {
                    "binding_rule": "original_heading_standalone",
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
                continue
        for structure in page_structures.get(block["page_no"], []):
            if not (
                structure["page_no"] == block["page_no"]
                and block["y0"] <= structure["y0"] < end
            ):
                continue
            binding = _build_binding_from_structure(structure, key)
            if normalize_compound(binding["cpd"]) != normalize_compound(block["cpd"]):
                # The shared builder cannot yet represent every printed-ID form.
                # Preserve the observation as unresolved, never shorten its owner.
                continue
            binding["binding_rule"] = "heading_range_fallback"
            binding["original_heading_evidence"] = dict(block)
            binding = _annotate_bindings_with_visible_labels([binding], cache)[0]
            # No parent/suffix matching and no confidence-selected winner.
            if _candidate_labels(binding, strict_only=True) != {key}:
                continue
            checked = annotate_binding_accuracy(binding)
            if checked.get("accuracy_status") == "confirmed" and not checked.get(
                "fail_closed"
            ):
                candidates.setdefault(key, {})[str(checked["structure_id"])] = checked
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
