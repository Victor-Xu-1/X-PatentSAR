"""Pure two-dimensional unruled source population; no distances or number order."""

from .activity_context_geometry import valid_box
from .structure_table_headers import structure_column_pairs
from .unruled_structure_headers import header_windows, unruled_header_roles
from .unruled_structure_sources import label_population


def _get_box(node, page_size):
    box = node.get("bbox")
    if (
        not valid_box(box)
        or not isinstance(box, list)
        or not 0 <= box[0] < box[2] <= page_size[0]
        or not 0 <= box[1] < box[3] <= page_size[1]
    ):
        raise ValueError("Malformed original unruled diagram geometry")
    return box


def region_plan(region):
    """Every source label/diagram remains present; only reciprocal unique rows bind."""
    if (
        not isinstance(region, dict)
        or set(region)
        != {
            "status",
            "version",
            "header_scope",
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
    roles = unruled_header_roles(scope)
    xs, ys = header_windows(scope["nomination"], scope["page_size"])
    bottom = region["body_bottom"]
    if type(bottom) not in {int, float} or not ys[1] < bottom <= scope["page_size"][1]:
        raise ValueError("Malformed original unruled body boundary")
    # Nomination is used only to retain unresolved source windows if full role
    # proof fails. It cannot authorize a binding.
    nominated = structure_column_pairs([g["text"] for g in scope["nomination"]])
    labels, qualified = label_population(region, xs, ys, bottom, nominated)
    diagrams = region["diagrams"]
    if (
        not isinstance(diagrams, list)
        or len(diagrams) > 25000
        or any(
            not isinstance(d, dict)
            or set(d) != {"id", "bbox"}
            or not isinstance(d["id"], str)
            or not d["id"]
            or len(d["id"]) > 256
            for d in diagrams
        )
        or len({d["id"] for d in diagrams}) != len(diagrams)
    ):
        raise ValueError("Malformed original unruled diagram inventory")
    for diagram in diagrams:
        _get_box(diagram, scope["page_size"])
    edges, reverse = [[] for _ in labels], [[] for _ in diagrams]
    if roles is not None and roles["role"] == "compound":
        for index, label in enumerate(labels):
            if not qualified[index]:
                continue
            identifier, structure = roles["pairs"][label["pair"]]
            box = label["nomination"]["bbox"]
            centre = (box[1] + box[3]) / 2
            for number, diagram in enumerate(diagrams):
                drawing = diagram["bbox"]
                if (
                    xs[identifier] <= box[0] < box[2] <= xs[identifier + 1]
                    and xs[structure] <= drawing[0] < drawing[2] <= xs[structure + 1]
                    and ys[1] <= drawing[1] < drawing[3] <= bottom
                    and drawing[1] <= centre <= drawing[3]
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
