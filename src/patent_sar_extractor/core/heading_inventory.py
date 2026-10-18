"""Original heading membership replay in the existing source-reference ledger."""

from .activity_header_evidence import proof_id
from .heading_group_scope import group_heading_members
from .heading_source_proof import heading_observation_status
from .printed_identifiers import identifier_key
from .source_binding_proof import annotate_source_binding
from .source_section_roles import heading_members

HEADING_ROLES = {
    "compound_heading",
    "assay_section",
    "intermediate_section",
    "ambiguous_heading",
    "unproved_heading",
    "figure_label_reference",
}


def heading_sections(sections):
    return [section for section in sections if section.get("role") in HEADING_ROLES]


def _heading_owners(entries, original_sha):
    """Current declarations require the same original occurrence, not an ID hit."""
    owners = set()
    for entry in entries:
        for source in [entry, *entry.get("additional_sources", [])]:
            if source.get("binding_rule") != "original_heading_standalone":
                continue
            checked = annotate_source_binding(source)
            if (
                checked.get("accuracy_status") == "confirmed"
                and not checked.get("fail_closed")
                and checked.get("source_pdf_sha256") == original_sha
            ):
                proof = checked["original_heading_structure_evidence"]["heading_source"]
                owners.add(
                    (proof_id(proof), identifier_key(checked.get("cpd"), wrapped=True))
                )
    return owners


def heading_inventory_issues(sections, scope, entries):
    headings = heading_sections(sections)
    if scope["version"] not in {3, 4, 5, 6}:
        if any("heading_observation" in section for section in headings):
            raise ValueError("Original heading inventory was downgraded")
        return []
    if scope.get("heading_ids") != [proof_id(section) for section in headings]:
        raise ValueError("Original heading inventory was omitted or changed")
    labels = {identifier_key(entry.get("cpd"), wrapped=True) for entry in entries}
    owners = (
        _heading_owners(entries, scope["original_pdf_sha256"])
        if scope["version"] == 6
        else set()
    )
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
            if "group_context" in section:
                raise ValueError("Unproved heading cannot assert a local group context")
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
        group_members = (
            group_heading_members(section, entries, scope["original_pdf_sha256"])
            if "group_context" in section
            else set()
        )
        if declaration["role"] in {
            "intermediate_section",
            "assay_section",
            "figure_label_reference",
        }:
            continue
        for identifier in heading_members(declaration):
            present = (
                ((proof_id(proof), identifier) in owners or identifier in group_members)
                if scope["version"] == 6
                else identifier in labels
            )
            if declaration["role"] == "ambiguous_heading" or not present:
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
