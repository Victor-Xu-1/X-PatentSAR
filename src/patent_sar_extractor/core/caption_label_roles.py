"""Exact original caption/identifier-cell roles in the existing source ledger."""

import re
from collections import defaultdict

from .activity_header_evidence import proof_id
from .caption_locator_proof import valid_locator_scope
from .caption_role_proof import caption_role_status
from .numbered_structure_pairs import _box
from .printed_identifiers import identifier_key
from .source_binding_proof import annotate_source_binding
from .source_cell_tokens import cell_tokens, crosses_cell
from .source_evidence_identity import SourceEvidenceLimit
from .source_section_roles import heading_members, section_heading

ROLE = "structure_label_reference"
PENDING_ROLE = "unresolved_structure_label_reference"
MAX_SOURCES = 25000


def caption_label_index(bindings, original_pdf_sha256):
    """Only full original cell proof supplies a role window, never flags/IDs."""
    output, count = defaultdict(dict), 0
    if not isinstance(bindings, (list, tuple)) or len(bindings) > MAX_SOURCES:
        raise ValueError("Original caption-role sources exceed their bound")
    for entry in bindings:
        if not isinstance(entry, dict):
            raise TypeError("Malformed original caption-role source")
        additional = entry.get("additional_sources", [])
        if not isinstance(additional, list) or len(additional) > 1000:
            raise ValueError("Malformed original caption-role reprints")
        for binding in (entry, *additional):
            count += 1
            if count > MAX_SOURCES or not isinstance(binding, dict):
                raise ValueError("Malformed or excessive original caption-role sources")
            rule = binding.get("binding_rule")
            if rule not in {"original_caption_cell", "numbered_structure_table_cell"}:
                continue
            if (
                not isinstance(original_pdf_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", original_pdf_sha256)
                or binding.get("source_pdf_sha256") != original_pdf_sha256
            ):
                continue
            checked = annotate_source_binding(binding)
            if checked.get("accuracy_status") != "confirmed" or checked.get(
                "fail_closed"
            ):
                continue
            field = (
                "exact_caption_evidence"
                if rule == "original_caption_cell"
                else "numbered_table_cell_evidence"
            )
            evidence = checked[field]
            bounds = (
                evidence["bbox"]
                if field == "exact_caption_evidence"
                else evidence["label_bbox"]
            )
            identifier = identifier_key(checked.get("cpd"), wrapped=True)
            key = proof_id(
                {
                    "status": "observed_original_caption"
                    if rule == "original_caption_cell"
                    else "observed_original_identifier_cell",
                    "original_pdf_sha256": original_pdf_sha256,
                    "identifier": identifier,
                    "structure_id": checked["structure_id"],
                    "page_no": checked["page_no"],
                    "structure_bbox": [
                        checked["struct_" + axis] for axis in ("x0", "y0", "x1", "y1")
                    ],
                    field: evidence,
                }
            )
            ownership = evidence.get("ownership") or {}
            physical = (
                list(bounds)
                if rule == "original_caption_cell"
                and ownership.get("kind") == "ruled_caption"
                and ownership.get("label_cell") == list(bounds)
                and evidence.get("reading_bbox", list(bounds)) == list(bounds)
                and caption_role_status(
                    ownership.get("caption_role"), evidence["page_no"], list(bounds)
                )
                == "compound"
                else None
            )
            output[evidence["page_no"]][key] = {
                "source_key": key,
                "identifier": identifier,
                "bbox": list(bounds),
                "original_pdf_sha256": original_pdf_sha256,
                "cell_bbox": physical,
            }
    return dict(output)


def owns_label_locator(box, cell):
    """Use the original cell SDK's centre and one-point locator edge budget.

    A layout detector's padding is not another original heading. This aliases
    only a locator to an already proved source; it never expands that source's
    observation window or accepts its molecule from a nearby label.
    """
    token = {"x": (box[0] + box[2]) / 2, "y": (box[1] + box[3]) / 2, "bbox": box}
    return bool(cell_tokens([token], cell)) and not crosses_cell([token], cell)


def caption_label_reference(
    line, page_no, index, *, physical_source=None, page_size=None
):
    """A matching literal must belong to one exact proved label window."""
    if (
        type(page_no) is not int
        or not isinstance(line.get("source"), str)
        or line.get("source") not in {"native", "page_ocr"}
        or line.get("geometry_space") != "rendered"
        or not isinstance(line.get("bbox"), (list, tuple))
        or len(line["bbox"]) != 4
        or any(type(v) not in {int, float} for v in line["bbox"])
    ):
        return None
    box = _box(line.get("bbox"))
    observed = section_heading(line.get("text"))
    members = heading_members(observed)
    if (
        not box
        or not observed
        or observed["role"] != "compound_heading"
        or len(members) != 1
    ):
        return None
    options = [
        source
        for source in index.get(page_no, {}).values()
        if source["identifier"] == members[0]
        and owns_label_locator(box, source["bbox"])
    ]
    physical = False
    if (
        not options
        and physical_source is not None
        and valid_locator_scope(physical_source, line, page_size)
    ):
        options = [
            source
            for source in index.get(page_no, {}).values()
            if source["cell_bbox"] == physical_source["cell"]
        ]
        physical = True
    if len(options) != 1:
        return None
    reference = {
        "role": ROLE,
        "status": "observed_source_reference",
        "page_no": page_no,
        "bbox": list(line["bbox"]),
        "line_text": line["text"],
        "line_source": line["source"],
        "geometry_space": "rendered",
        "identifier": options[0]["identifier"],
        "source_key": options[0]["source_key"],
        "original_pdf_sha256": options[0]["original_pdf_sha256"],
        **(
            {"physical_source": physical_source, "page_size": page_size}
            if physical
            else {}
        ),
    }
    if physical:
        try:
            proof_id(reference)
        except SourceEvidenceLimit:
            return None  # Keep the occurrence on the ordinary unresolved path.
    return reference


def caption_reference_ids(sections):
    return [
        proof_id(section)
        for section in sections
        if section.get("role") in {ROLE, PENDING_ROLE}
    ]


def validate_caption_references(sections, scope, entries):
    references = [section for section in sections if section.get("role") == ROLE]
    if scope["version"] < 5:
        if references or any(
            section.get("role") == PENDING_ROLE for section in sections
        ):
            raise ValueError("Original label-role reference inventory was downgraded")
        return
    if scope.get("label_reference_ids") != caption_reference_ids(sections):
        raise ValueError("Original label-role references were omitted or changed")
    if not references:
        return
    if not scope["original_pdf_sha256"]:
        raise ValueError("Original label-role references have no document identity")
    index = caption_label_index(entries, scope["original_pdf_sha256"])
    for section in references:
        expected = caption_label_reference(
            {
                "text": section.get("line_text"),
                "source": section.get("line_source"),
                "geometry_space": section.get("geometry_space"),
                "bbox": section.get("bbox"),
            },
            section.get("page_no"),
            index,
            physical_source=section.get("physical_source"),
            page_size=section.get("page_size"),
        )
        if expected is None or expected != section:
            raise ValueError("Unproved original label-role reference ownership")
