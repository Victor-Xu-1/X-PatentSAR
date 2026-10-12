"""Project the existing shared conventions and validate only new submissions."""

from collections import defaultdict

from ..activity_rank_values import rank_direction
from ..errors import WebError
from .indicator_models import IndicatorDefault


def context_default(context: dict) -> IndicatorDefault:
    direction, rule = rank_direction(
        context["name"],
        context.get("unit"),
        context.get("context", {}).get("assay"),
        "numeric",
    )
    return IndicatorDefault(direction=direction, rule=rule)


def setup_defaults(contexts: list[dict]):
    policies = {context["id"]: context_default(context) for context in contexts}
    groups = defaultdict(list)
    for context in contexts:
        groups[context["metric_id"]].append(policies[context["id"]])
    metrics = {}
    for identifier, defaults in groups.items():
        metrics[identifier] = (
            defaults[0]
            if all(value == defaults[0] for value in defaults)
            else IndicatorDefault(direction="unknown", rule="mixed_contexts")
        )
    return policies, metrics


def validate_direction(context: dict, direction: str) -> None:
    expected = context_default(context).direction
    if expected != "unknown" and direction != expected:
        raise WebError(
            422,
            "sar_indicator_direction",
            "The requested direction contradicts this endpoint's established convention.",
        )
