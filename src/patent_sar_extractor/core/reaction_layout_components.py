"""Complete local source components, before any proposed wrap interpretation."""

from collections import defaultdict

from .reaction_arrows import segment_bounds
from .reaction_heads import head_bounds


def local_components(page, diagrams, report, groups):
    parents = {drawing["structure_id"]: drawing["structure_id"] for drawing in diagrams}

    def root(identity):
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    grouped = {group["step_index"]: group["input_ids"] for group in groups}
    edges = []
    for index, step in enumerate(report["steps"]):
        if step["from"] is None and step["to"] is None:
            raise ValueError("A wholly unowned arrow cannot supply a wrapped route")
        if step["from"] is not None and step["to"] is not None:
            for first in grouped.get(index, [step["from"]]):
                last = step["to"]
                parents[root(first)] = root(last)
                edges.append((first, last))
    parts = {}
    for drawing in diagrams:
        identity = drawing["structure_id"]
        part = parts.setdefault(
            root(identity),
            {
                "page_no": page["page_no"],
                "structure_ids": [],
                "step_indices": [],
                "boxes": [],
                "inputs": [],
                "outputs": [],
            },
        )
        part["structure_ids"].append(identity)
        part["boxes"].append(drawing["bbox"])
    incoming, outgoing = defaultdict(set), defaultdict(set)
    for first, last in edges:
        outgoing[first].add(last)
        incoming[last].add(first)
    for index, step in enumerate(report["steps"]):
        part = parts[root(step["from"] or step["to"])]
        part["step_indices"].append(index)
        part["boxes"].extend(
            segment_bounds(page["segments"][i]) for i in step["segments"]
        )
        part["boxes"].extend(
            head_bounds(page["filled_heads"][i]) for i in step["heads"]
        )
        for name, plural in (("input_port", "inputs"), ("output_port", "outputs")):
            if step[name] is not None:
                part[plural].append(index)
                part["boxes"].append(step[name]["corridor"])
    result = []
    for part in parts.values():
        boxes = part.pop("boxes")
        part["bbox"] = [
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ]
        part["roots"] = [sid for sid in part["structure_ids"] if not incoming[sid]]
        part["terminals"] = [sid for sid in part["structure_ids"] if not outgoing[sid]]
        result.append(part)
    return sorted(result, key=lambda part: (part["bbox"][1], part["bbox"][0]))


def component_reference(part):
    return {
        key: part[key] for key in ("page_no", "bbox", "structure_ids", "step_indices")
    }
