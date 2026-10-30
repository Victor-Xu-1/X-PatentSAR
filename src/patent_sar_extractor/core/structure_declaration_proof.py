"""Independent declaration coverage in the existing original-source acceptance."""

from collections import defaultdict

from .activity_context_geometry import context_region, grid_box
from .activity_header_evidence import proof_id
from .binding_source_regions import reference_cell
from .declaration_reference_ownership import characterization_owns_catalogue_title
from .printed_identifiers import identifier_key
from .source_binding_proof import annotate_source_binding
from .source_window_chunks import validate_source_overlap
from .structure_declaration_columns import original_logical_columns
from .structure_declaration_continuations import physical_declaration_columns
from .structure_declaration_roles import (
    declaration_label_reference,
    declaration_role_index,
)
from .structure_declaration_scopes import (
    PAGE_ROLE,
    PAGE_STATUS,
    REFERENCE_ROLE,
    declaration_scopes,
    declaration_scopes_with_identity,
    nonfinal_declaration_diagrams,
)
from .unruled_body_scope import body_context_window


def declaration_ids(sections, role):
    return [
        s.get("region_id") if role == PAGE_ROLE else proof_id(s)
        for s in sections
        if s.get("role") == role
    ]


def _pages(sections, scope, *, current=False):
    pages = [s for s in sections if s.get("role") == PAGE_ROLE]
    refs = [s for s in sections if s.get("role") == REFERENCE_ROLE]
    if scope["version"] < 6:
        if pages or refs:
            raise ValueError("Original declaration inventory was downgraded")
        return []
    if scope.get("declaration_page_ids") != declaration_ids(
        sections, PAGE_ROLE
    ) or scope.get("declaration_reference_ids") != declaration_ids(
        sections, REFERENCE_ROLE
    ):
        raise ValueError("Original declarations were omitted or changed")
    if refs and not pages:
        raise ValueError("Original declaration references have no source page")
    parents_by_page = defaultdict(list)
    for parent in sections:
        if parent.get("role") in {
            "unruled_structure_region",
            "structure_column_anchor",
        }:
            parents_by_page[parent["page_no"]].append(parent)
    seen = set()
    for section in pages:
        source = section.get("source")
        identity, _scopes = declaration_scopes_with_identity(source)
        expected_columns = original_logical_columns(parents_by_page[section["page_no"]])
        expected_continued = physical_declaration_columns(
            parents_by_page[section["page_no"]]
        )
        if current and source["version"] != (
            4 if expected_continued else 3 if expected_columns else 2
        ):
            raise ValueError(
                "Current original declarations require the complete catalogue scopes"
            )
        if (current or source["version"] in {3, 4}) and source.get(
            "logical_columns", []
        ) != expected_columns:
            raise ValueError(
                "Original logical-column declaration inventory was omitted or changed"
            )
        if (current or source["version"] == 4) and source.get(
            "continued_columns", []
        ) != expected_continued:
            raise ValueError(
                "Original physical-continuation declarations were omitted or changed"
            )
        if (
            set(section) != {"role", "status", "page_no", "region_id", "source"}
            or not isinstance(source, dict)
            or section["region_id"] != identity
            or section["status"] != PAGE_STATUS
            or type(section["page_no"]) is not int
            or section["page_no"] != source.get("page_no")
            or source.get("original_pdf_sha256") != scope["original_pdf_sha256"]
            or section["page_no"] in seen
        ):
            raise ValueError("Malformed original declaration identity")
        seen.add(section["page_no"])
        for parent in parents_by_page[section["page_no"]]:
            old = parent["source"]
            header = old["header_scope"]
            if header.get("kind") == "original_ruled_columns":
                geometry = context_region(
                    header["grid_axes"], [grid_box(g) for g in source["page_grids"]]
                )["context_geometry"]
                if header["context_geometry"] != geometry:
                    raise ValueError(
                        "Original header context differs from the page grid inventory"
                    )
            elif header.get("kind") in {None, "continued_ruled_columns"}:
                if header["page_grids"] != source["page_grids"]:
                    raise ValueError(
                        "Original column scope changed the complete page grid inventory"
                    )
            if old["page_diagrams"] != source["page_diagrams"]:
                raise ValueError(
                    "Original declaration dropped or changed page diagrams"
                )
            validate_source_overlap(
                source["page_context"],
                [0, 0, *source["page_size"]],
                old["body_context"],
                body_context_window(old["header_scope"]),
            )
    return pages


def declaration_issues(
    sections, scope, entries, *, nonfinal_diagrams, title_payload=None, current=False
):
    pages = _pages(sections, scope, current=current)
    from .title_source_inventory import validate_title_page_inventory

    validate_title_page_inventory(
        title_payload
        if title_payload is not None
        else {
            "bindings": list(entries),
            "source_sections": sections,
        },
        pages,
    )
    if not pages:
        return []
    roles = declaration_role_index(pages, scope["original_pdf_sha256"])
    for reference in sections:
        if reference.get("role") != REFERENCE_ROLE:
            continue
        expected = declaration_label_reference(
            {
                "text": reference.get("line_text"),
                "source": reference.get("line_source"),
                "geometry_space": reference.get("geometry_space"),
                "bbox": reference.get("bbox"),
            },
            reference.get("page_no"),
            roles,
        )
        if expected is None or reference != expected:
            raise ValueError("Unproved nonfinal declaration reference")
    accepted, identifiers = defaultdict(list), set()
    for entry in entries:
        for row in [entry, *entry.get("additional_sources", [])]:
            checked = annotate_source_binding(row)
            if (
                checked.get("accuracy_status") == "confirmed"
                and not checked.get("fail_closed")
                and checked.get("source_pdf_sha256") == scope["original_pdf_sha256"]
            ):
                accepted[row["structure_id"]].append(row)
                identifiers.add(identifier_key(row.get("cpd"), wrapped=True))
    issues = []
    reference_regions = defaultdict(list)
    for section in sections:
        if section.get("role") == "characterization_region":
            reference_regions[section["page_no"]].append(section["source_region"])
    for page in pages:
        for original in declaration_scopes(page["source"]):
            role = original["role"]
            finding = {
                "cpd": "",
                "page_no": original["page_no"],
                "source_region": original["source_region"],
            }
            issues.extend(
                {
                    **finding,
                    "reason": "unproved_original_section_boundary",
                    "boundary": boundary,
                }
                for boundary in original["unproved_boundaries"]
            )
            if original["unproved_nonfinal_role"]:
                issues.append(
                    {**finding, "reason": "unproved_original_nonfinal_declaration"}
                )
            if original["unproved_title"] and not characterization_owns_catalogue_title(
                original, page["source"], reference_regions[original["page_no"]]
            ):
                issues.append(
                    {**finding, "reason": "unproved_original_catalogue_title"}
                )
            excluded = {d["id"] for d in nonfinal_declaration_diagrams(original)}
            for diagram in original["diagrams"]:
                owners = [
                    row
                    for row in accepted[diagram["id"]]
                    if row.get("page_no") == original["page_no"]
                    and [row.get("struct_" + k) for k in ("x0", "y0", "x1", "y1")]
                    == diagram["bbox"]
                ]
                nonfinal = diagram["id"] in excluded
                if (nonfinal or role == "conflict") and owners:
                    raise ValueError(
                        "Original nonfinal or conflicting declaration was promoted"
                    )
                if (
                    not nonfinal
                    and diagram["id"] not in nonfinal_diagrams
                    and not owners
                ):
                    issues.append(
                        {
                            **finding,
                            "structure_id": diagram["id"],
                            "reason": "declared_original_diagram_without_proved_identifier",
                        }
                    )
            if role == "conflict":
                issues.append(
                    {**finding, "reason": "conflicting_original_table_declaration"}
                )
            # The raw candidates stay in the complete original scope. A known
            # method/characterization cell is not a new terminal declaration,
            # even when a wrapped line happens to be just "Compound <ID>".
            lists = [
                {
                    **item,
                    "identifiers": [
                        key
                        for key, line in zip(
                            item["identifiers"], item["lines"], strict=True
                        )
                        if reference_cell(
                            line,
                            reference_regions[original["page_no"]],
                            permitted_roles=frozenset(
                                {"preparation", "characterization"}
                            ),
                        )
                        is None
                    ],
                }
                for item in original["identifier_lists"]
            ]
            if lists and (
                any(
                    not item["qualified"] or not all(item["identifiers"])
                    for item in lists
                )
                or any(
                    item["identifiers"] != lists[0]["identifiers"] for item in lists[1:]
                )
            ):
                issues.append(
                    {**finding, "reason": "conflicting_original_identifier_list"}
                )
            for key in sorted(
                {key for item in lists for key in item["identifiers"] if key}
                - identifiers
            ):
                issues.append(
                    {
                        **finding,
                        "cpd": f"Compound {key}",
                        "reason": "declared_original_identifier_without_proved_structure",
                    }
                )
    return issues
