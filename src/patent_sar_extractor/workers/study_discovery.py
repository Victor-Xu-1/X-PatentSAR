"""Native, input-bound candidate planning in the existing study worker."""

from patent_sar_extractor.core.sar.discovery import comparison_plan
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.web.sar.assets import atomic_json, digest


def native_plan(safe, identity, rows, regions, dataset, request, check):
    plans, coverage = comparison_plan(rows, regions, dataset, request, check)
    if request.get("discover_single_sites", False):
        value = {**identity, "plans": plans, "coverage": coverage}
        value["plan_sha256"] = digest([plans, coverage])
        existing = safe.json("network-plan.json")
        if existing is not None and existing != value:
            raise SARInputError("study_discovery_checkpoint_identity")
        if existing is None:
            atomic_json(safe.root, "network-plan.json", value)
    return plans, coverage
