"""Remove broad automatic duplicates ONLY after a stricter complete proof."""

from .errors import SARInputError
from .matching import compile_reference


def _inside(small, large):
    left, right = small["region"], large["region"]
    if left.get("hydrogen_anchor") is not None:
        return left["hydrogen_anchor"] in right["atom_indices"]
    return bool(left["atom_indices"]) and set(left["atom_indices"]) < set(
        right["atom_indices"]
    )


def compact_proved_sites(
    plans,
    rows,
    pool,
    check,
    *,
    pair_budget=None,
    site_budget=None,
):
    """Consume smallest-region-first plans through one cancellable proof path."""
    if any(
        budget is not None and (type(budget) is not int or budget < 0)
        for budget in (pair_budget, site_budget)
    ):
        raise SARInputError("study_discovery_pair_limit")
    by_id = {row["id"]: row for row in rows}
    groups, retained, removed = {}, [], 0
    prior_order, comparisons = None, 0
    for plan in plans:
        check()
        region = plan["region"]
        order = len(region["atom_indices"]), region["id"]
        if prior_order is not None and order < prior_order:
            raise ValueError("Site reduction requires smallest-first proof order")
        prior_order = order
        key = region["molecule_id"], tuple(plan["candidate_ids"])
        alternatives = groups.setdefault(key, [])
        dominated = False
        for prior in alternatives:
            if not _inside(prior["plan"], plan):
                continue
            if prior["proved"] is None:
                smaller = prior["plan"]["region"]
                matcher = compile_reference(
                    by_id[smaller["molecule_id"]]["molfile"],
                    smaller["atom_indices"],
                    hydrogen_anchor=smaller.get("hydrogen_anchor"),
                    pool=pool,
                )
                valid = True
                for candidate_id in prior["plan"]["candidate_ids"]:
                    check()
                    if (
                        matcher.compare(by_id[candidate_id]["molfile"])["match_status"]
                        != "matched"
                    ):
                        valid = False
                        break
                prior["proved"] = valid
            if prior["proved"]:
                dominated = True
                break
        if dominated:
            removed += 1
        else:
            retained.append(plan)
            alternatives.append({"plan": plan, "proved": None})
            comparisons += len(plan["candidate_ids"])
            # Narrow-first proof means later/larger proposals cannot replace
            # these retained sites. Charge once, only after unchanged strict
            # duplicate proof. No larger numeric budget or partial output.
            if (
                pair_budget is not None
                and comparisons > pair_budget
                or site_budget is not None
                and len(retained) > site_budget
            ):
                raise SARInputError("study_discovery_pair_limit")
    return retained, removed
