"""Separate supplied physicochemical/model evidence, never an acceptance score."""

from __future__ import annotations

from decimal import Decimal

from patent_sar_extractor.core.sar.study_priority import pareto_fronts
from patent_sar_extractor.core.sar.values import Value
from patent_sar_extractor.web.lead_endpoints import LEAD_ENDPOINTS


def secondary_evidence(rows: list[dict], check=lambda: None) -> dict[str, tuple]:
    """Only break activity-front ties; compare the same verified endpoint set.

    Model probabilities are relative research evidence, not measured toxicity.
    Imported/unavailable predictions never become zero risk. Large-molecule
    flags reuse the existing Lead chemistry's review boundaries, not a veto.
    """
    groups: dict[tuple, dict[str, tuple[Value, ...]]] = {}
    keys: dict[str, tuple[int, ...]] = {}
    for row in rows:
        properties = row["properties"]
        physical = [
            properties.get(key)
            for key in (
                "molecular_weight",
                "logP",
                "tpsa",
                "hydrogen_bond_donors",
                "hydrogen_bond_acceptors",
            )
        ]
        coverage = sum(value is not None for value in physical)
        review = any(
            value is not None and value > limit
            for value, limit in zip(physical[:3], (800, 6, 200), strict=True)
        )
        row["reasons"].append(
            "physchem_review_large_or_lipophilic"
            if review
            else "physchem_values_descriptive"
        )
        if coverage < 5:
            row["reasons"].append("physchem_evidence_incomplete")
        predictions = row["predictions"]
        known = tuple(
            sorted(
                key
                for key, value in predictions.items()
                if key in LEAD_ENDPOINTS and value is not None and 0 <= value <= 1
            )
        )
        verified = row["prediction_origin"] == "verified_project_model" and bool(known)
        keys[row["molecule_id"]] = (int(not verified), 0, -coverage, int(review))
        if verified and row["pareto_front"] is not None:
            group = row["pareto_front"], known
            groups.setdefault(group, {})[row["molecule_id"]] = tuple(
                Value(
                    "scalar",
                    Decimal(str(predictions[key])),
                    Decimal(str(predictions[key])),
                )
                for key in known
            )
            row["reasons"].append("predictions_current_model_not_experimental")
            if len(known) != len(LEAD_ENDPOINTS):
                row["reasons"].append("prediction_evidence_partial")
            if any(
                predictions[key] >= 0.8
                for key in known
                if LEAD_ENDPOINTS[key] == "lower"
            ):
                row["reasons"].append("predicted_liability_requires_review")
        else:
            row["reasons"].append("prediction_evidence_unknown_or_unverified")
    by_id = {row["molecule_id"]: row for row in rows}
    for (_, endpoints), vectors in groups.items():
        policies = [
            {"direction": LEAD_ENDPOINTS[key], "grade_order": []} for key in endpoints
        ]
        fronts = pareto_fronts(vectors, policies, check)
        for identifier, front in fronts.items():
            # Fronts with DIFFERENT endpoint coverage are not inter-comparable.
            # Endpoint coverage is explicit evidence priority, never a zero fill.
            prior = keys[identifier]
            keys[identifier] = (prior[0], -len(endpoints), front, *prior[2:])
            by_id[identifier]["reasons"].append(f"predicted_evidence_front_{front}")
    return keys
