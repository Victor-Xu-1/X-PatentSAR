"""Source-cell-linked conditions for SAR, reusing the existing provenance parser."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ...core.pipeline_rules import _label_key
from ..activity_provenance import metric_unit, source_evidence
from ..artifact_values import page_number, text
from ..errors import WebError
from ..files import SafeFiles, records
from ..models import Activity
from .assets import digest


def owner_key(value: str) -> str:
    return _label_key(value) or value


def _condition_bytes(project: dict) -> tuple[bytes | None, str]:
    """Bind the actual original condition bytes, not just flattened DTO rows."""
    if (
        not project["run_root"]
        or not project["sha256"]
        or project["sha256"] != project["expected_sha256"]
    ):
        return None, digest(["no-verified-condition-source"])

    try:
        data = SafeFiles(Path(project["run_root"])).read(
            "activity/activity_data.json", max_bytes=32 * 1024 * 1024
        )
    except WebError as error:
        if error.code == "asset_unavailable":
            return None, digest(["condition-source-missing"])
        raise
    return data, hashlib.sha256(data).hexdigest()


def conditions_sha256(project: dict) -> str:
    return _condition_bytes(project)[1]


def _nonfinite(value: str):
    raise ValueError("Nonfinite condition source")


class ObservationContexts:
    def __init__(self, project: dict):
        self.exact: dict[tuple, dict[str, dict]] = {}
        self.metric: dict[tuple, dict[str, dict]] = {}
        data, self.source_sha256 = _condition_bytes(project)
        if data is None:
            return
        try:
            payload = json.loads(data, parse_constant=_nonfinite)
        except (ValueError, RecursionError, UnicodeError) as error:
            raise WebError(
                422, "invalid_artifact", "Condition source JSON is invalid."
            ) from error
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
