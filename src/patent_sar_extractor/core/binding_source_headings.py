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
from .heading_evidence import (
    heading_identifier,
    original_heading_lines,
    standalone_heading_evidence,
)
from .pipeline_rules import _candidate_labels, annotate_binding_accuracy


def _document_sha256(doc) -> str:
    """Label observations can include pixels outside the molecule crop."""
    if doc.name and not doc.is_dirty:
        with Path(doc.name).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    return hashlib.sha256(doc.tobytes(no_new_id=True)).hexdigest()


def observed_heading_blocks(doc, pages: list[int], line_map: dict) -> list[dict]:
    """Coordinates and complete labels originate in the source, not an ID list."""
    blocks = []
    for page_index in sorted(set(pages)):
        observed = original_heading_lines(doc[page_index], line_map.get(page_index, []))
        for line in observed:
            label = heading_identifier(line["text"])
            if label:
                blocks.append(
                    {
                        "cpd": f"Compound {label}",
                        "page_no": page_index + 1,
                        "y0": line["y0"],
                        "y1": line["y1"],
                        "bbox": line["bbox"],
                        "line_text": line["text"],
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
) -> tuple[list[dict], list[dict]]:
    """Require mutually unique crop/printed-label proof in an observed interval."""
    if not structures or not blocks:
        return [], [
            {"cpd": b["cpd"], "page_no": b["page_no"], "reason": "no_heading_structure"}
            for b in blocks
        ]
    document_sha256 = _document_sha256(doc)
    structures = [
        {**structure, "source_pdf_sha256": document_sha256} for structure in structures
    ]
    cache = _load_visible_label_cache(output_dir, profile)
    cache = _refine_visible_label_cache_with_page_ocr(
        structures, cache, line_map, output_dir, profile
    )
    candidates = {}
    for index, block in enumerate(blocks):
        key = normalize_compound(block["cpd"]).removeprefix("Compound ")
        next_block = blocks[index + 1] if index + 1 < len(blocks) else None
        end = (
            next_block["y0"]
            if next_block and next_block["page_no"] == block["page_no"]
            else doc[block["page_no"] - 1].rect.height
        )
        page = doc[block["page_no"] - 1]
        direct, evidence = standalone_heading_evidence(
            page,
            block,
            structures,
            original_heading_lines(page, line_map.get(block["page_no"] - 1, [])),
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
        for structure in structures:
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
