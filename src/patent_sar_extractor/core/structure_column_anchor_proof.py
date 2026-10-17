"""Replay registered original column anchors in current saved consumers."""

from collections import defaultdict

from .activity_header_evidence import proof_id
from .ruled_structure_proof import validate_ruled_source_reference
from .structure_column_anchors import ANCHOR_ROLE, column_anchor_roles
from .structure_column_population import column_population_issues


def validate_column_anchors(sections, scope, entries):
    anchors = [s for s in sections if s.get("role") == ANCHOR_ROLE]
    if scope["version"] < 6:
        if anchors:
            raise ValueError("Original column-anchor inventory was downgraded")
        return [], []
    if scope.get("column_anchor_ids") != [s.get("region_id") for s in anchors]:
        raise ValueError("Original column anchors were omitted or changed")
    known, issues, roles_by_id, represented = {}, [], {}, defaultdict(list)
    present = {
        row["structure_id"]
        for entry in entries
        for row in [entry, *entry.get("additional_sources", [])]
        if isinstance(row.get("structure_id"), str)
    }
    for section in anchors:
        source = section.get("source")
        if (
            set(section) != {"role", "status", "page_no", "region_id", "source"}
            or not isinstance(source, dict)
            or section["region_id"] != proof_id(source)
            or section["region_id"] in known
        ):
            raise ValueError("Malformed original column-anchor identity")
        roles = column_anchor_roles(source)
        header = source["header_scope"]
        if (
            section["status"] != source["status"]
            or type(section["page_no"]) is not int
            or section["page_no"] != header["page_no"]
            or header["original_pdf_sha256"] != scope["original_pdf_sha256"]
        ):
            raise ValueError("Foreign original column-anchor frame")
        known[section["region_id"]] = section
        roles_by_id[section["region_id"]] = roles
        if roles is None:
            issues.append(
                {
                    "cpd": "",
                    "page_no": section["page_no"],
                    "reason": "unproved_original_ruled_header",
                    "source_region": section["region_id"],
                }
            )
        if roles is None or roles["role"] == "nonfinal":
            grid = source["grid_axes"]
            start = int(header.get("kind") == "original_ruled_columns")
            excluded = {
                d["id"]
                for d in source["page_diagrams"]
                if grid["xs"][0] <= d["bbox"][0] < d["bbox"][2] <= grid["xs"][-1]
                and grid["ys"][start]
                <= d["bbox"][1]
                < d["bbox"][3]
                <= min(grid["ys"][-1], source["body_bottom"])
            }
            if present & excluded:
                raise ValueError(
                    "Unproved or nonfinal original grid was promoted to final structures"
                )
    for entry in entries:
        for row in [entry, *entry.get("additional_sources", [])]:
            evidence = row.get("numbered_table_cell_evidence") or {}
            if not isinstance(evidence, dict):
                raise ValueError("Malformed original ruled cell evidence")  # noqa: TRY004 -- shared source-schema boundary
            if evidence.get("kind") != "original_ruled_columns":
                continue
            ownership = evidence.get("column_ownership")
            if (
                not isinstance(ownership, dict)
                or not isinstance(ownership.get("source_anchor_id"), str)
                or not isinstance(ownership.get("header_scope"), dict)
            ):
                raise ValueError("Missing original ruled column-anchor scope")  # noqa: TRY004 -- shared source-schema boundary
            parent = known.get(ownership["source_anchor_id"])
            if (
                parent is None
                or parent["page_no"] != row["page_no"]
                or parent["source"]["header_scope"] != ownership["header_scope"]
                or parent["source"]["grid_axes"] != ownership.get("grid_axes")
            ):
                raise ValueError("Ruled binding has no exact original column anchor")
            validate_ruled_source_reference(parent, row)
            represented[
                (parent["region_id"], evidence["row"], evidence["pair"])
            ].append(row)
    for section in anchors:
        issues.extend(
            column_population_issues(
                section, roles_by_id[section["region_id"]], represented
            )
        )
    return anchors, issues
