"""Local original unruled ownership and whole-source ledger replay."""

import re

from .activity_context_geometry import valid_box
from .activity_header_evidence import proof_id
from .cell_identity_proof import confirmed_identity_readings
from .printed_identifiers import identifier_key
from .source_cell_claims import cell_source_status
from .structure_column_anchor_proof import validate_column_anchors
from .unruled_continuation_links import (
    uncovered_continuation_issues,
    validate_continuation_links,
)
from .unruled_scope import scope_roles
from .unruled_structure_layout import (
    original_column_overlap,
    pair_evidence,
    region_plan,
)


def valid_unruled_binding(binding):
    evidence = binding.get("numbered_table_cell_evidence")
    if not isinstance(evidence, dict) or set(evidence) != {
        "kind",
        "coordinate_space",
        "source_region_id",
        "body_bottom",
        "page_no",
        "source_label",
        "label_index",
        "diagram_index",
        "label_bbox",
        "segment_bbox",
        "structure_id",
        "header_scope",
        "row_label",
        "row_diagrams",
    }:
        return False
    try:
        roles = scope_roles(evidence["header_scope"])
        label = evidence["row_label"]
        if (
            roles is None
            or roles["role"] != "compound"
            or evidence["kind"] != "original_unruled_columns"
            or evidence["coordinate_space"] != "rendered_pdf_points"
            or not isinstance(evidence["source_region_id"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", evidence["source_region_id"])
        ):
            return False
        if (
            not isinstance(label, dict)
            or type(label.get("pair")) is not int
            or not 0 <= label["pair"] < len(roles["pairs"])
            or type(label.get("needs_review")) is not bool
            or label["needs_review"]
        ):
            return False
        for name in ("page_no", "label_index", "diagram_index"):
            if type(evidence[name]) is not int or not 0 <= evidence[name] <= 25000:
                return False
        scope = evidence["header_scope"]
        if (
            binding.get("source_pdf_sha256") != scope["original_pdf_sha256"]
            or evidence["page_no"] != scope["page_no"]
            or type(binding.get("page_no")) is not int
            or binding["page_no"] != evidence["page_no"]
        ):
            return False
        nominal = label["nomination"]
        box = nominal["bbox"]
        window, diagram = evidence["label_bbox"], evidence["segment_bbox"]
        xs, ys = roles["xs"], roles["ys"]
        identifier, structure = roles["pairs"][label["pair"]]
        bottom = evidence["body_bottom"]
        if (
            not valid_box(box)
            or not valid_box(window)
            or not valid_box(diagram)
            or type(bottom) not in {int, float}
            or not ys[1] < bottom <= scope["page_size"][1]
        ):
            return False
        if (
            window != nominal["window"]
            or window
            != [
                xs[identifier],
                max(ys[1], box[1] - 4),
                xs[identifier + 1],
                min(bottom, box[3] + 4),
            ]
            or not original_column_overlap(
                box, diagram, xs, ys, (identifier, structure), bottom
            )
        ):
            return False
        if (
            evidence["structure_id"] != binding.get("structure_id")
            or diagram != [binding.get("struct_" + k) for k in ("x0", "y0", "x1", "y1")]
            or evidence["row_diagrams"]
            != [{"id": evidence["structure_id"], "bbox": diagram}]
        ):
            return False
        value = identifier_key(label["value"], wrapped=True, terminal_period=True)
        if (
            not value
            or value != evidence["source_label"]
            or value
            != identifier_key(binding.get("cpd"), wrapped=True, terminal_period=True)
        ):
            return False
        observations = label["observations"]
        if (
            not isinstance(observations, list)
            or not 1 <= len(observations) <= 4
            or not any(
                isinstance(o, dict)
                and "source_observation" in o
                and o.get("bbox") == window
                and cell_source_status(o) in {"qualified", "unqualified", "empty"}
                for o in observations
            )
        ):
            return False
        if any(
            not isinstance(o, dict) or o.get("bbox", window) != window
            for o in observations
        ):
            return False
        return confirmed_identity_readings(value, observations)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False


def unruled_source_inventory(sections, scope, entries):
    """One replay supplies findings and positively proved nonfinal diagrams."""
    anchors, anchor_issues, nonfinal = validate_column_anchors(sections, scope, entries)
    regions = [s for s in sections if s.get("role") == "unruled_structure_region"]
    if scope["version"] < 6:
        if regions:
            raise ValueError("Original unruled source inventory was downgraded")
        return anchor_issues, nonfinal
    if scope.get("unruled_region_ids") != [s.get("region_id") for s in regions]:
        raise ValueError("Original unruled source regions were omitted or changed")
    sources = [
        source
        for entry in entries
        for source in [entry, *entry.get("additional_sources", [])]
    ]
    by_id = {s.get("structure_id"): s for s in sources}
    known, issues, expected_sources = set(), list(anchor_issues), {}
    for section in regions:
        if (
            set(section) != {"role", "status", "page_no", "region_id", "source"}
            or not isinstance(section["source"], dict)
            or section["region_id"] in known
            or section["region_id"] != proof_id(section["source"])
        ):
            raise ValueError("Malformed original unruled source identity")
        region = section["source"]
        known.add(section["region_id"])
        if (
            section["status"] != region.get("status")
            or type(section["page_no"]) is not int
            or section["page_no"] != region["header_scope"]["page_no"]
            or region["header_scope"]["original_pdf_sha256"]
            != scope["original_pdf_sha256"]
        ):
            raise ValueError("Foreign original unruled source frame")
        roles, assignments, findings = region_plan(region)
        expected_sources[section["region_id"]] = {}
        issues.extend(
            {
                **finding,
                "page_no": section["page_no"],
                "source_region": section["region_id"],
            }
            for finding in findings
        )
        if (
            roles is not None
            and roles["role"] == "nonfinal"
            and any(d["id"] in by_id for d in region["diagrams"])
        ):
            raise ValueError(
                "Original unruled intermediates were promoted to final compounds"
            )
        if roles is not None and roles["role"] == "nonfinal":
            nonfinal.update(d["id"] for d in region["diagrams"])
        for label, diagram in assignments:
            expected = pair_evidence(region, section["region_id"], label, diagram)
            expected_sources[section["region_id"]][expected["structure_id"]] = expected
            source = by_id.get(expected["structure_id"])
            if source is None:
                issues.append(
                    {
                        "cpd": expected["source_label"],
                        "page_no": section["page_no"],
                        "reason": "unruled_identifier_without_proved_structure",
                    }
                )
            elif source.get("numbered_table_cell_evidence") != expected:
                raise ValueError(
                    "Unruled binding differs from its complete original source"
                )
    validate_continuation_links([*anchors, *regions])
    issues.extend(uncovered_continuation_issues([*anchors, *regions]))
    for source in sources:
        evidence = source.get("numbered_table_cell_evidence") or {}
        if (
            evidence.get("kind") == "original_unruled_columns"
            and evidence.get("source_region_id") not in known
        ):
            raise ValueError("Unruled binding has no original source ledger")
        if (
            evidence.get("kind") == "original_unruled_columns"
            and expected_sources[evidence["source_region_id"]].get(
                source.get("structure_id")
            )
            != evidence
        ):
            raise ValueError("Unruled binding has no canonical original assignment")
    return issues, nonfinal
