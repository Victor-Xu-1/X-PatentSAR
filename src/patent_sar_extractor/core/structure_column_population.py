"""Conserve every observed physical row without trusting saved total counts."""

from bisect import bisect_left, bisect_right
from collections import defaultdict

from .printed_identifiers import identifier_key
from .source_cell_tokens import cell_text, grid_token_index
from .source_window_chunks import window_source_tokens
from .unruled_body_scope import body_context_window


def _diagram_cell_index(diagrams, xs, ys):
    result = defaultdict(list)
    for diagram in diagrams:
        box = diagram["bbox"]
        for row in range(
            max(0, bisect_right(ys, box[1]) - 1),
            min(len(ys) - 1, bisect_left(ys, box[3])),
        ):
            for col in range(
                max(0, bisect_right(xs, box[0]) - 1),
                min(len(xs) - 1, bisect_left(xs, box[2])),
            ):
                result[(row, col)].append(diagram)
    return result


def column_population_issues(section, roles, represented):
    if roles is None:
        return []  # The independently replayed unknown-header issue already blocks QA.
    source, issues = section["source"], []
    scope, grid = source["header_scope"], source["grid_axes"]
    xs, ys = grid["xs"], grid["ys"]
    window = body_context_window(scope)
    lanes = [
        grid_token_index(
            window_source_tokens(source["body_context"], window, native=native), xs, ys
        )
        for native in (False, True)
    ]
    diagrams = _diagram_cell_index(source["page_diagrams"], xs, ys)
    first = int(scope.get("kind") == "original_ruled_columns")
    for row in range(first, len(ys) - 1):
        for pair, (identifier, structure) in enumerate(roles["pairs"]):
            labels = [
                cell_text(
                    lane.get((row, identifier), []),
                    [xs[identifier], ys[row], xs[identifier + 1], ys[row + 1]],
                )
                for lane in lanes
            ]
            candidates = diagrams.get((row, structure), [])
            if not candidates and not any(text.strip() for text in labels):
                continue
            if roles["role"] == "nonfinal" and ys[row + 1] <= source["body_bottom"]:
                continue
            consumers = represented.get((section["region_id"], row, pair), [])
            outside = ys[row + 1] > source["body_bottom"]
            unique = (
                len(candidates) == 1
                and xs[structure]
                <= candidates[0]["bbox"][0]
                < candidates[0]["bbox"][2]
                <= xs[structure + 1]
                and ys[row]
                <= candidates[0]["bbox"][1]
                < candidates[0]["bbox"][3]
                <= ys[row + 1]
            )
            if len(consumers) == 1 and unique and not outside:
                continue
            if consumers:
                raise ValueError(
                    "Ruled binding contradicts its complete original cell population"
                )
            known = {
                identifier_key(text, wrapped=True, terminal_period=True)
                for text in labels
            } - {""}
            issues.append(
                {
                    "cpd": "Compound " + next(iter(known)) if len(known) == 1 else "",
                    "page_no": section["page_no"],
                    "reason": "original_ruled_row_without_proved_structure"
                    if not outside
                    else "original_ruled_row_after_source_boundary",
                    "source_region": section["region_id"],
                    "row": row,
                    "pair": pair,
                    "observed_labels": labels,
                    "observed_structures": [d["id"] for d in candidates],
                }
            )
    return issues
