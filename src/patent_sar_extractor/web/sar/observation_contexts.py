"""Source-cell-linked conditions for SAR, reusing the existing provenance parser."""

from __future__ import annotations

from pathlib import Path

from ...core.pipeline_rules import _label_key
from ..activity_provenance import metric_unit, source_evidence
from ..artifact_values import page_number, text
from ..files import SafeFiles, records
from ..models import Activity
from .assets import digest


def owner_key(value: str) -> str:
    return _label_key(value) or value


class ObservationContexts:
    def __init__(self, project: dict):
        self.exact: dict[tuple, dict[str, dict]] = {}
        self.metric: dict[tuple, dict[str, dict]] = {}
        if (
            not project["run_root"]
            or not project["sha256"]
            or project["sha256"] != project["expected_sha256"]
        ):
            return
        payload = SafeFiles(Path(project["run_root"])).json(
            "activity/activity_data.json"
        )
        for row in records(payload, "rows"):
            owner = owner_key(text(row.get("cpd")) or "")
            fallback = (
                page_number(row.get("page_no")),
                text(row.get("target")),
                text(row.get("assay")),
            )
            sources = source_evidence(row, fallback, page_count=project["page_count"])
            if not sources:
                conditions = {
                    key: row.get(key)
                    for key in (
                        "cell_line",
                        "construct",
                        "duration",
                        "treatment_duration",
                        "timepoint",
                        "batch",
                    )
                    if key in row
                }
                if any(
                    value is not None
                    and (not isinstance(value, str) or len(value) > 1000)
                    for value in conditions.values()
                ):
                    from ..activity_provenance import provenance_error

                    raise provenance_error()
                for field in ("activity_values", "cell_line_data"):
                    for name, value in (row.get(field) or {}).items():
                        self._add(
                            owner, name, text(value, limit=1001), fallback, conditions
                        )
                continue
            for source in sources:
                owners = {
                    owner_key(cell.value or "")
                    for cell in source.cells
                    if cell.name == "compound_id"
                }
                if owners and owners != {owner}:
                    continue
                for cell in source.cells:
                    if cell.name != "compound_id":
                        self._add(
                            owner,
                            cell.name,
                            cell.value,
                            source.context,
                            dict(source.conditions),
                        )

    def _add(self, owner, name, value, context, conditions) -> None:
        if not owner or not name:
            return
        packet = {
            "target": context[1],
            "assay": context[2],
            "cell_line": None,
            "duration": None,
            **conditions,
        }
        if (
            packet.get("duration") is None
            and packet.get("treatment_duration") is not None
        ):
            packet["duration"] = packet.pop("treatment_duration")
        key = (owner, context[0], name, metric_unit(name), context[1], context[2])
        self.exact.setdefault((*key, value), {})[digest(packet)] = packet
        self.metric.setdefault(key, {})[digest(packet)] = packet

    def contexts(self, identifier: str, activity: Activity) -> list[dict]:
        key = (
            owner_key(identifier),
            activity.page,
            activity.name,
            activity.unit,
            activity.target,
            activity.assay,
        )
        # A numeric-only audited edit retains its metric-owned known conditions.
        # Multiple possible conditions stay separate, never averaged into unknown.
        values = self.exact.get(
            (*key, text(activity.value, limit=1001))
        ) or self.metric.get(key)
        return (
            list(values.values())
            if values
            else [
                {
                    "target": activity.target,
                    "assay": activity.assay,
                    "cell_line": None,
                    "duration": None,
                }
            ]
        )
