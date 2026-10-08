"""Pure complete-membership scaffold and strict-region descriptive summaries."""

from __future__ import annotations

import hashlib
from typing import Any

from .study_statistics import distribution


def scaffold_summaries(
    descriptors: list[dict], observations: dict, policy: dict, assessments: dict
) -> list[dict]:
    groups: dict[str, dict[str, Any]] = {}
    for row in descriptors:
        key = row["scaffold_id"]
        if key is None:
            key = hashlib.sha256(b"study_structure_unavailable").hexdigest()
        group = groups.setdefault(
            key, {"id": key, "smiles": row["scaffold_smiles"], "molecule_ids": []}
        )
        group["molecule_ids"].append(row["molecule_id"])
    return [
        {
            **group,
            "molecule_count": len(group["molecule_ids"]),
            "strong_count": sum(
                assessments[item]["strong"] for item in group["molecule_ids"]
            ),
            "bins": distribution(
                group["molecule_ids"], observations, policy, assessments
            )["bins"],
            "descriptive_only": True,
        }
        for group in groups.values()
    ]


def region_summary(
    region: dict,
    reference: dict,
    reference_fragment: dict,
    pairs: list[dict],
    fragments: dict[str, dict],
    observations: dict,
    policy: dict,
    assessments: dict,
) -> dict:
    groups = {
        reference_fragment["id"]: {
            "id": reference_fragment["id"],
            "smiles": reference_fragment["smiles"],
            "molecule_ids": [reference["id"]],
            "better": 0,
            "worse": 0,
            "indeterminate": 0,
            "missing": 0,
            "is_reference": True,
        }
    }
    statuses = {
        name: 0 for name in ("matched", "not_matched", "ambiguous", "ineligible")
    }
    comparable = 0
    for pair in pairs:
        statuses[pair["match_status"]] += 1
        if pair["match_status"] != "matched":
            continue
        fragment = fragments[pair["fragment_id"]]
        group = groups.setdefault(
            fragment["id"],
            {
                "id": fragment["id"],
                "smiles": fragment["smiles"],
                "molecule_ids": [],
                "better": 0,
                "worse": 0,
                "indeterminate": 0,
                "missing": 0,
                "is_reference": fragment["id"] == reference_fragment["id"],
            },
        )
        group["molecule_ids"].append(pair["molecule_id"])
        comparison = pair["comparison"]
        if comparison in {"better", "worse", "missing"}:
            group[comparison] += 1
        elif comparison != "equal":
            group["indeterminate"] += 1
        comparable += comparison in {"better", "worse", "equal"}
    result = []
    for group in groups.values():
        members = group["molecule_ids"]
        result.append(
            {
                **group,
                "molecule_count": len(members),
                "strong_count": sum(assessments[item]["strong"] for item in members),
                "bins": distribution(members, observations, policy, assessments)[
                    "bins"
                ],
            }
        )
    return {
        "region": region,
        "reference_label": reference["label"],
        "reference_fragment_id": reference_fragment["id"],
        "fixed_background_sha256": reference_fragment["fixed_background_sha256"],
        **statuses,
        "comparable": comparable,
        "no_variation": len(groups) == 1,
        "fragments": result,
        "independent_backgrounds": 1,
    }
