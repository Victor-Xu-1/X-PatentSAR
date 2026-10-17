"""Exact original caption references in the existing source-role ledger."""

import re
from collections import defaultdict

from .activity_header_evidence import proof_id
from .numbered_structure_pairs import _box
from .printed_identifiers import identifier_key
from .source_binding_proof import annotate_source_binding
from .source_section_roles import heading_members, section_heading

ROLE = "structure_label_reference"
MAX_SOURCES = 25000


def caption_label_index(bindings, original_pdf_sha256):
    """Only full original caption proof supplies a role window, never flags/IDs."""
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
            if binding.get("binding_rule") != "original_caption_cell":
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
            evidence = checked["exact_caption_evidence"]
            identifier = identifier_key(checked.get("cpd"), wrapped=True)
            key = proof_id(
                {
                    "status": "observed_original_caption",
                    "original_pdf_sha256": original_pdf_sha256,
                    "identifier": identifier,
                    "structure_id": checked["structure_id"],
                    "page_no": checked["page_no"],
                    "structure_bbox": [
                        checked["struct_" + axis] for axis in ("x0", "y0", "x1", "y1")
                    ],
                    "exact_caption_evidence": evidence,
                }
            )
            output[(evidence["page_no"], identifier)][key] = {
                "source_key": key,
                "identifier": identifier,
                "bbox": list(evidence["bbox"]),
                "original_pdf_sha256": original_pdf_sha256,
            }
    return dict(output)


def caption_label_reference(line, page_no, index):
    """A matching literal must be inside one exact proved label window."""
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
        for source in index.get((page_no, members[0]), {}).values()
        if source["bbox"][0] <= box[0] < box[2] <= source["bbox"][2]
        and source["bbox"][1] <= box[1] < box[3] <= source["bbox"][3]
    ]
    if len(options) != 1:
        return None
    return {
        "role": ROLE,
        "status": "observed_source_reference",
        "page_no": page_no,
        "bbox": list(line["bbox"]),
        "line_text": line["text"],
        "line_source": line["source"],
        "geometry_space": "rendered",
        "identifier": members[0],
        "source_key": options[0]["source_key"],
        "original_pdf_sha256": options[0]["original_pdf_sha256"],
    }


def caption_reference_ids(sections):
    return [proof_id(section) for section in sections if section.get("role") == ROLE]


def validate_caption_references(sections, scope, entries):
    references = [section for section in sections if section.get("role") == ROLE]
    if scope["version"] < 5:
        if references:
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
        )
        if expected is None or expected != section:
            raise ValueError("Unproved original label-role reference ownership")
