"""Original heading membership replay in the existing source-reference ledger."""

from .activity_header_evidence import proof_id
from .heading_source_proof import heading_observation_status
from .printed_identifiers import identifier_key
from .source_section_roles import heading_members

HEADING_ROLES = {
    "compound_heading",
    "assay_section",
    "intermediate_section",
    "ambiguous_heading",
    "unproved_heading",
}


def heading_sections(sections):
    return [section for section in sections if section.get("role") in HEADING_ROLES]


def heading_inventory_issues(sections, scope, entries):
    headings = heading_sections(sections)
    if scope["version"] != 3:
        if any("heading_observation" in section for section in headings):
            raise ValueError("Original heading inventory was downgraded")
        return []
    if scope.get("heading_ids") != [proof_id(section) for section in headings]:
        raise ValueError("Original heading inventory was omitted or changed")
    labels = {identifier_key(entry.get("cpd"), wrapped=True) for entry in entries}
    issues = []
    for section in headings:
        proof = section.get("heading_observation")
        status, declaration = heading_observation_status(proof)
        if status == "invalid" or (
            proof.get("status") != status
            or section.get("status") != status
            or not scope["original_pdf_sha256"]
            or proof["original_pdf_sha256"] != scope["original_pdf_sha256"]
            or type(section.get("page_no")) is not int
            or section["page_no"] != proof["page_no"]
            or section.get("bbox") != proof["nomination"]["bbox"]
        ):
            raise ValueError("Malformed original heading source proof")
        if status == "unresolved":
            if section["role"] != "unproved_heading":
                raise ValueError("Unproved original heading has an asserted role")
            issues.append(
                {
                    "cpd": "",
                    "page_no": section["page_no"],
                    "reason": "unproved_original_heading",
                }
            )
            continue
        if any(section.get(key) != value for key, value in declaration.items()):
            raise ValueError(
                "Original heading declaration differs from its observations"
            )
        if declaration["role"] in {"intermediate_section", "assay_section"}:
            continue
        for identifier in heading_members(declaration):
            if declaration["role"] == "ambiguous_heading" or identifier not in labels:
                issues.append(
                    {
                        "cpd": f"Compound {identifier}",
                        "page_no": section["page_no"],
                        "reason": "ambiguous_original_heading"
                        if declaration["role"] == "ambiguous_heading"
                        else "original_heading_identifier_without_proved_structure",
                    }
                )
    return issues
