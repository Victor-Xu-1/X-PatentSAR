"""Bounded strict-context Pareto fronts; no decimal lead/author score."""

from __future__ import annotations

from .errors import SARInputError
from .values import Value, grade_ranks

MAX_RANKABLE = 5000


def _cost(value: Value, policy: dict) -> tuple:
    if value.kind == "ordinal":
        return (grade_ranks(policy["grade_order"])[value.grade],)
    low, high = value.numeric_bounds()
    return (low, high) if policy["direction"] == "lower" else (-high, -low)


def _dominates(
    left: tuple[Value, ...], right: tuple[Value, ...], policies: list[dict]
) -> bool:
    better = False
    for a, b, policy in zip(left, right, policies, strict=True):
        if a.kind == b.kind == "ordinal":
            ranks = grade_ranks(policy["grade_order"])
            if ranks[a.grade] > ranks[b.grade]:
                return False
            better |= ranks[a.grade] < ranks[b.grade]
        elif a.kind == b.kind == "scalar" and a.low == b.low:
            continue
        elif (policy["direction"] == "lower" and a.high < b.low) or (
            policy["direction"] == "higher" and a.low > b.high
        ):
            better = True
        else:
            # Overlapping/equal censored intervals are NOT quantitative ties.
            return False
    return better


def pareto_fronts(
    vectors: dict[str, tuple[Value, ...]], policies: list[dict], check=lambda: None
) -> dict[str, int]:
    """At most 5000 rankable rows, O(N*K) storage, never an N*N matrix.

    Identical observed vectors share a front (not an inferred numeric value).
    Lexicographic ordering guarantees all provable dominators precede a node;
    streaming depth yields exact successive non-dominated fronts.
    """
    if len(vectors) > MAX_RANKABLE:
        raise SARInputError("study_ranking_limit")
    unique: dict[tuple[Value, ...], list[str]] = {}
    for identifier, vector in vectors.items():
        unique.setdefault(vector, []).append(identifier)
    ordered = sorted(
        unique,
        key=lambda vector: tuple(
            _cost(v, p) for v, p in zip(vector, policies, strict=True)
        ),
    )
    completed: list[tuple[tuple[Value, ...], int]] = []
    result = {}
    for vector in ordered:
        check()
        depth = 1
        for index, (previous, front) in enumerate(completed):
            if index % 128 == 0:
                check()
            if _dominates(previous, vector, policies):
                depth = max(depth, front + 1)
        completed.append((vector, depth))
        for identifier in unique[vector]:
            result[identifier] = depth
    return result


def select_candidates(
    rows: list[dict],
    count: int,
    features: dict,
    similarity,
    check=lambda: None,
    *,
    identities=None,
    evidence=None,
) -> list[dict]:
    """Front/coverage/recorded evidence first; diversity only breaks such ties.

    Unknown fingerprints are never assigned zero similarity (fake novelty).
    Predictions and absent properties are not converted to safety or scores.
    """
    remaining = [row for row in rows if row["pareto_front"] is not None]
    selected: list[dict] = []
    identities = identities or {row["molecule_id"]: row["molecule_id"] for row in rows}
    evidence = evidence or {}
    while remaining and len(selected) < count:
        check()
        key = lambda row: (
            row["pareto_front"],
            -row["coverage"],
            evidence.get(row["molecule_id"], ()),
        )
        best = min(key(row) for row in remaining)
        pool = [row for row in remaining if key(row) == best]
        known_selected = [
            features[row["molecule_id"]]
            for row in selected
            if row["molecule_id"] in features
        ]
        if known_selected:
            known_pool = [row for row in pool if row["molecule_id"] in features]
            if known_pool:
                pool = sorted(
                    known_pool,
                    key=lambda row: max(
                        similarity(features[row["molecule_id"]], other)
                        for other in known_selected
                    ),
                )
        chosen = pool[0]
        chosen.update(candidate_status="selected", selection_order=len(selected) + 1)
        selected.append(chosen)
        identity = identities[chosen["molecule_id"]]
        aliases = [
            row
            for row in remaining
            if identities[row["molecule_id"]] == identity and row is not chosen
        ]
        for row in aliases:
            row["reasons"].append("graph_identical_selection_alias")
        remaining = [
            row for row in remaining if identities[row["molecule_id"]] != identity
        ]
    return selected
