"""Replay original characterization references in the single binding artifact."""

import re

from .activity_header_evidence import proof_id
from .binding_source_diagnostics import binding_diagnostic_issues
from .binding_source_regions import identifier_references, reference_cell
from .caption_label_roles import (
    PENDING_ROLE,
    caption_reference_ids,
    validate_caption_references,
)
from .caption_pending_roles import validate_pending_caption_references
from .caption_role_proof import validate_caption_exclusions
from .heading_inventory import heading_inventory_issues, heading_sections
from .printed_identifiers import identifier_key
from .reference_region_identity import reference_region_id
from .source_fragment_links import resolved_fragments
from .source_geometry import _box
from .source_role_fragments import fragment_issues
from .source_role_observations import validate_role_catalog
from .source_section_roles import section_heading
from .structure_declaration_proof import declaration_ids, declaration_issues
from .structure_declaration_scopes import PAGE_ROLE, REFERENCE_ROLE
from .title_geometry_memo import title_geometry_call
from .unruled_structure_proof import unruled_source_inventory

MAX_SOURCE_SECTIONS = 25000
_SHA = re.compile(r"[0-9a-f]{64}")


def reference_scope(sections, original_pdf_sha256=""):
    regions = [
        section["source_region"]
        for section in sections
        if section["role"] == "characterization_region"
    ]
    origins = (
        {region["original_pdf_sha256"] for region in regions}
        | {
            section["source"]["original_pdf_sha256"]
            for section in sections
            if section.get("role") == PAGE_ROLE
        }
        | {
            section["heading_observation"]["original_pdf_sha256"]
            for section in heading_sections(sections)
            if isinstance(section.get("heading_observation"), dict)
        }
        | {
            section["original_pdf_sha256"]
            for section in sections
            if section.get("role") in {"structure_label_reference", PENDING_ROLE}
            and isinstance(section.get("original_pdf_sha256"), str)
        }
        | {
            section["source"]["header_scope"]["original_pdf_sha256"]
            for section in sections
            if section.get("role")
            in {"unruled_structure_region", "structure_column_anchor"}
        }
    )
    if not original_pdf_sha256 and len(origins) == 1:
        original_pdf_sha256 = next(iter(origins))
    return {
        "version": 6,
        "original_pdf_sha256": original_pdf_sha256,
        "region_ids": [region["region_id"] for region in regions],
        "caption_region_ids": [
            proof_id(section)
            for section in sections
            if section["role"] == "nonfinal_caption_catalog"
        ],
        "heading_ids": [proof_id(section) for section in heading_sections(sections)],
        "label_reference_ids": caption_reference_ids(sections),
        "unruled_region_ids": [
            s["region_id"]
            for s in sections
            if s.get("role") == "unruled_structure_region"
        ],
        "column_anchor_ids": [
            s["region_id"]
            for s in sections
            if s.get("role") == "structure_column_anchor"
        ],
        "declaration_page_ids": declaration_ids(sections, PAGE_ROLE),
        "declaration_reference_ids": declaration_ids(sections, REFERENCE_ROLE),
    }


def _regions(sections, scope):
    if (
        not isinstance(scope, dict)
        or set(scope)
        != (
            {
                "version",
                "original_pdf_sha256",
                "region_ids",
                "caption_region_ids",
                "heading_ids",
            }
            | ({"label_reference_ids"} if scope.get("version") in {5, 6} else set())
            | (
                {
                    "unruled_region_ids",
                    "column_anchor_ids",
                    "declaration_page_ids",
                    "declaration_reference_ids",
                }
                if scope.get("version") == 6
                else set()
            )
            if scope.get("version") in {3, 4, 5, 6}
            else {"version", "original_pdf_sha256", "region_ids", "caption_region_ids"}
            if scope.get("version") == 2
            else {"version", "original_pdf_sha256", "region_ids"}
        )
        or type(scope["version"]) is not int
        or scope["version"] not in {1, 2, 3, 4, 5, 6}
        or not isinstance(scope["original_pdf_sha256"], str)
        or scope["original_pdf_sha256"]
        and not _SHA.fullmatch(scope["original_pdf_sha256"])
        or not isinstance(scope["region_ids"], list)
        or len(scope["region_ids"]) > MAX_SOURCE_SECTIONS
    ):
        raise ValueError("Malformed original binding reference scope")
    captions = [
        section
        for section in sections
        if section.get("role") == "nonfinal_caption_catalog"
    ]
    if (
        scope["version"] == 1
        and captions
        or scope["version"] in {2, 3, 4, 5, 6}
        and scope.get("caption_region_ids")
        != [proof_id(section) for section in captions]
    ):
        raise ValueError(
            "Original nonfinal caption inventory differs or was downgraded"
        )
    regions = {}
    for section in sections:
        if section.get("role") != "characterization_region":
            continue
        region = section.get("source_region")
        if (
            not isinstance(region, dict)
            or set(region)
            != (
                {
                    "page_no",
                    "bbox",
                    "role_scope",
                    "status",
                    "original_pdf_sha256",
                    "geometry_space",
                    "region_id",
                }
                | (
                    {"grid_edges", "row_fragments", "fragment_context"}
                    if scope["version"] in {4, 5, 6}
                    else set()
                )
            )
            or type(region["page_no"]) is not int
            or not 1 <= region["page_no"] <= 20000
            or type(section.get("page_no")) is not int
            or section.get("page_no") != region["page_no"]
            or region["geometry_space"] != "rendered"
            or not scope["original_pdf_sha256"]
            or region["original_pdf_sha256"] != scope["original_pdf_sha256"]
            or region["status"] != "observed_characterization"
            or not isinstance(region["region_id"], str)
            or region["region_id"] in regions
        ):
            raise ValueError("Unproved original binding reference region")
        _box(region["bbox"])
        if region["region_id"] != reference_region_id(
            {key: value for key, value in region.items() if key != "region_id"}
        ):
            raise ValueError("Original characterization-region identity differs")
        regions[region["region_id"]] = region
    if scope["region_ids"] != list(regions):
        raise ValueError("Original binding reference region coverage differs")
    return regions


@title_geometry_call
def reference_issues(payload, entries, *, required=True):
    sections = payload.get("source_sections", [])
    if (
        not isinstance(sections, list)
        or len(sections) > MAX_SOURCE_SECTIONS
        or any(
            not isinstance(section, dict) or not isinstance(section.get("role"), str)
            for section in sections
        )
    ):
        raise ValueError("Malformed bounded original binding sections")
    scope = payload.get("source_reference_scope")
    validate_role_catalog(
        payload.get("source_role_observations", {}),
        original_pdf_sha256=(scope.get("original_pdf_sha256") or None)
        if isinstance(scope, dict)
        else None,
    )
    diagnostic_issues = binding_diagnostic_issues(
        payload.get("source_role_observations", {}), payload.get("source_issues", ())
    )
    validate_caption_exclusions(sections, entries)
    if (
        scope is None
        and not required
        and not any(
            section.get("role", "").startswith("characterization_")
            or section.get("role")
            in {
                "unruled_structure_region",
                "structure_label_reference",
                PENDING_ROLE,
                "structure_column_anchor",
                PAGE_ROLE,
                REFERENCE_ROLE,
            }
            for section in sections
        )
    ):
        return diagnostic_issues
    regions = _regions(sections, scope)
    if required and scope["version"] != 6:
        raise ValueError(
            "Current original source inventory requires unruled-column coverage"
        )
    validate_caption_references(sections, scope, entries)
    validate_pending_caption_references(
        sections, scope, payload.get("source_role_observations", {})
    )
    expected = [
        reference
        for region in regions.values()
        for reference in identifier_references(region)
    ]
    actual = [
        section
        for section in sections
        if section.get("role") == "characterization_identifier"
    ]
    for reference in actual:
        if any(
            type(reference.get(field)) is not int
            for field in ("page_no", "grid_row", "grid_column")
        ):
            raise ValueError("Invalid original reference cell coordinate types")
        _box(reference.get("bbox"))
    if actual != expected:
        raise ValueError("Original primary reference cells were omitted or changed")
    for section in sections:
        if section.get("role") != "characterization_reference":
            continue
        if any(
            type(section.get(field)) is not int
            for field in ("page_no", "grid_row", "grid_column")
        ):
            raise ValueError("Invalid original method-reference coordinate types")
        region = regions.get(section.get("source_region"))
        observed = section_heading(section.get("line_text"))
        if (
            region is None
            or observed is None
            or section.get("page_no") != region["page_no"]
        ):
            raise ValueError("Original method reference has no proved region")
        owner = reference_cell(
            {
                "bbox": section.get("bbox"),
                "text": section["line_text"],
                "source": section.get("line_source"),
                "geometry_space": section.get("geometry_space"),
            },
            [region],
        )
        if (
            owner is None
            or any(section.get(key) != value for key, value in owner.items())
            or section.get("identifier") != observed["identifier"]
            or section.get("label_kind") != observed["label_kind"]
        ):
            raise ValueError("Unproved original method-reference cell ownership")
    labels = {identifier_key(entry.get("cpd"), wrapped=True) for entry in entries}
    issues = [*diagnostic_issues, *heading_inventory_issues(sections, scope, entries)]
    column_issues, nonfinal_diagrams = unruled_source_inventory(
        sections, scope, entries
    )
    issues.extend(column_issues)
    issues.extend(
        declaration_issues(
            sections,
            scope,
            entries,
            nonfinal_diagrams=nonfinal_diagrams,
            title_payload=payload,
            current=required,
        )
    )
    issues.extend(
        fragment_issues(regions.values(), resolved_fragments(regions.values()))
    )
    for reference in expected:
        role = reference["source_role"]
        if (
            role == "ambiguous"
            or role == "terminal_reference"
            and reference["identifier"] not in labels
        ):
            issues.append(
                {
                    "cpd": f"Compound {reference['identifier']}"
                    if reference["identifier"]
                    else "",
                    "page_no": reference["page_no"],
                    "source_region": reference["source_region"],
                    "grid_row": reference["grid_row"],
                    "grid_column": reference["grid_column"],
                    "reason": "conflicting_characterization_identifier"
                    if role == "ambiguous"
                    else "characterization_identifier_without_proved_structure",
                }
            )
    return issues
