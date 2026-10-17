"""Pure two-dimensional unruled source population; no distances or number order."""

from .structure_table_headers import structure_column_pairs
from .unruled_body_scope import body_diagrams, original_body_bottom
from .unruled_scope import scope_axes, scope_headers, scope_roles
from .unruled_structure_sources import label_population


def original_column_overlap(label, drawing, xs, ys, pair, bottom):
    """Actual word/drawing extents must intersect within their original roles."""
    identifier, structure = pair
    return (
        xs[identifier] <= label[0] < label[2] <= xs[identifier + 1]
        and xs[structure] <= drawing[0] < drawing[2] <= xs[structure + 1]
        and ys[1] <= drawing[1] < drawing[3] <= bottom
        and min(label[3], drawing[3]) > max(label[1], drawing[1])
    )


def region_plan(region):
    """Every source label/diagram remains present; only reciprocal unique rows bind."""
    if (
        not isinstance(region, dict)
        or set(region)
        != {
            "status",
            "version",
            "header_scope",
            "body_context",
            "page_diagrams",
            "body_bottom",
            "pair_sources",
            "labels",
            "diagrams",
        }
        or region["status"] != "observed_original_unruled_columns"
        or type(region["version"]) is not int
        or region["version"] != 1
    ):
        raise ValueError("Malformed original unruled source region")
    scope = region["header_scope"]
    roles = scope_roles(scope)
    xs, ys = scope_axes(scope)
    bottom = region["body_bottom"]
    if type(bottom) not in {int, float} or not ys[1] < bottom <= scope["page_size"][1]:
        raise ValueError("Malformed original unruled body boundary")
    if bottom != original_body_bottom(
        scope, region["body_context"], region["page_diagrams"]
    ):
        raise ValueError(
            "Original unruled body boundary differs from its complete context"
        )
    # Nomination is used only to retain unresolved source windows if full role
    # proof fails. It cannot authorize a binding.
    nominated = structure_column_pairs(scope_headers(scope))
    labels, qualified = label_population(region, xs, ys, bottom, nominated)
    diagrams = region["diagrams"]
    if diagrams != body_diagrams(scope, bottom, region["page_diagrams"]):
        raise ValueError(
            "Original unruled diagrams differ from their complete page scope"
        )
    edges, reverse = [[] for _ in labels], [[] for _ in diagrams]
    if roles is not None and roles["role"] == "compound":
        for index, label in enumerate(labels):
            if not qualified[index]:
                continue
            box = label["nomination"]["bbox"]
            for number, diagram in enumerate(diagrams):
                drawing = diagram["bbox"]
                if original_column_overlap(
                    box, drawing, xs, ys, roles["pairs"][label["pair"]], bottom
                ):
                    edges[index].append(number)
                    reverse[number].append(index)
    pairs = [
        (index, numbers[0])
        for index, numbers in enumerate(edges)
        if len(numbers) == 1 and reverse[numbers[0]] == [index]
    ]
    accepted_labels = {a for a, _ in pairs}
    accepted_diagrams = {b for _, b in pairs}
    issues = []
    if roles is None:
        issues.append({"cpd": "", "reason": "unproved_original_unruled_header"})
    if scope.get("kind") == "continued_unruled_columns" and not labels and not diagrams:
        issues.append(
            {"cpd": "", "reason": "unproved_original_unruled_continuation_population"}
        )
    if roles is None or roles["role"] != "nonfinal":
        issues.extend(
            {
                "cpd": labels[index]["value"],
                "reason": "unbound_original_unruled_identifier",
            }
            for index in range(len(labels))
            if index not in accepted_labels
        )
        issues.extend(
            {
                "cpd": "",
                "structure_id": diagrams[index]["id"],
                "reason": "unlabelled_or_ambiguous_original_unruled_structure",
            }
            for index in range(len(diagrams))
            if index not in accepted_diagrams
        )
    return roles, pairs, issues


def pair_evidence(region, region_id, label_index, diagram_index):
    label, diagram = region["labels"][label_index], region["diagrams"][diagram_index]
    return {
        "kind": "original_unruled_columns",
        "coordinate_space": "rendered_pdf_points",
        "source_region_id": region_id,
        "body_bottom": region["body_bottom"],
        "page_no": region["header_scope"]["page_no"],
        "source_label": label["value"],
        "label_index": label_index,
        "diagram_index": diagram_index,
        "label_bbox": label["nomination"]["window"],
        "segment_bbox": diagram["bbox"],
        "structure_id": diagram["id"],
        "header_scope": region["header_scope"],
        "row_label": label,
        "row_diagrams": [diagram],
    }
