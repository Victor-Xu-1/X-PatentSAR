"""Remove broad automatic duplicates ONLY after a stricter complete proof."""

from .matching import compile_reference


def _inside(small, large):
    left, right = small["region"], large["region"]
    if left.get("hydrogen_anchor") is not None:
        return left["hydrogen_anchor"] in right["atom_indices"]
    return bool(left["atom_indices"]) and set(left["atom_indices"]) < set(
        right["atom_indices"]
    )


def compact_proved_sites(plans, rows, pool, check):
    by_id = {row["id"]: row for row in rows}
    groups, retained, removed = {}, [], 0
    for plan in sorted(
        plans,
        key=lambda item: (len(item["region"]["atom_indices"]), item["region"]["id"]),
    ):
        check()
        region = plan["region"]
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
    # Retain stable source/region order, not proof evaluation order.
    keep = {item["region"]["id"] for item in retained}
    return [item for item in plans if item["region"]["id"] in keep], removed
