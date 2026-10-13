"""Shared molecule assembly and exact-identity repeat handling for both inputs."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict

from ...core.sar.chemistry import prepare_structure
from ...core.sar.measurements import explicit_unit_basis
from ..errors import WebError
from ..storage import encode
from .models import Molecule, Observation

MAX_DATASET_BYTES = 32 * 1024 * 1024


def analysis_molecules(molecules: list[Molecule]) -> list[Molecule]:
    """Prepare new-analysis units without mutating any persisted source record.

    Both project and CSV snapshots use this path, including older datasets.
    An absent metadata unit can use the unit explicitly written in that reading;
    bare/unknown values cannot borrow a unit from another molecule or experiment.
    """
    result = []
    for molecule in molecules:
        observations = []
        changed = False
        for observation in molecule.observations:
            basis = (
                explicit_unit_basis(observation.value)
                if not (observation.unit or "").strip()
                else None
            )
            if basis:
                changed = True
                observation = observation.model_copy(update={"unit": basis})
            observations.append(observation)
        result.append(
            molecule.model_copy(update={"observations": observations})
            if changed
            else molecule
        )
    return result


class InputBudget:
    """Bound accumulated prepared graphs before retaining a whole large input."""

    def __init__(self):
        self.rows = self.bytes = 0

    def add(self, molecule: Molecule) -> None:
        self.rows += 1
        self.bytes += len(molecule.model_dump_json().encode())
        if self.rows > 25000 or self.bytes > MAX_DATASET_BYTES:
            raise WebError(
                413,
                "sar_dataset_limit",
                "Prepared SAR input exceeds its complete-record limit; no records were truncated.",
            )


def metric_key(
    name: str, unit: str | None, target: str | None, assay: str | None
) -> str:
    return hashlib.sha256(encode([name, unit, target, assay]).encode()).hexdigest()


def molecule_record(
    index: int,
    label: str,
    smiles: str | None,
    observations: list[Observation],
    molfile: str | None = None,
    issues: list[str] | None = None,
    **source,
) -> tuple[Molecule, str | None]:
    prepared = prepare_structure(smiles, molfile)
    findings = list(dict.fromkeys([*(issues or []), *prepared["issues"]]))
    if not label.strip() or len(label) > 200 or any(ord(c) < 32 for c in label):
        findings.append("missing_or_invalid_identifier")
    record = Molecule(
        id=f"m{index:06d}",
        label=label,
        smiles=prepared["smiles"],
        molfile=prepared["molfile"],
        graph_sha256=prepared["graph_sha256"],
        eligible=prepared["eligible"] and not findings,
        issues=list(dict.fromkeys(findings)),
        observations=observations,
        **source,
    )
    return record, prepared.get("chemical_sha256")


def merge_identical(records: list[tuple[Molecule, str | None]]) -> list[Molecule]:
    groups: dict[str, list[tuple[Molecule, str | None]]] = defaultdict(list)
    for record in records:
        groups[record[0].label].append(record)
    output = []
    for group in groups.values():
        first, chemical = group[0]
        if len(group) == 1:
            output.append(first)
        elif chemical is not None and all(
            item[1] == chemical and item[0].eligible for item in group
        ):
            observations = [obs for item, _ in group for obs in item.observations]
            if len(observations) > 2000:
                raise WebError(
                    413,
                    "sar_observation_limit",
                    "One identifier has more than 2000 observations; none were truncated.",
                )
            evidence = {}
            origins = dict(first.property_origins)
            for field in ("properties", "predictions"):
                merged = {}
                for key in {key for item, _ in group for key in getattr(item, field)}:
                    supplied = [
                        getattr(item, field)[key]
                        for item, _ in group
                        if key in getattr(item, field)
                    ]
                    merged[key] = (
                        supplied[0]
                        if all(value == supplied[0] for value in supplied)
                        else None
                    )
                    if (
                        field == "properties"
                        and merged[key] is None
                        and len(set(supplied)) > 1
                    ):
                        origins[key] = "conflicting_imported"
                evidence[field] = merged
            if any(
                len({item.predictions.get(key) for item, _ in group}) > 1
                for key in evidence["predictions"]
            ):
                evidence["prediction_origin"] = "conflicting_imported"
            output.append(
                first.model_copy(
                    update={
                        "observations": observations,
                        "property_origins": origins,
                        **evidence,
                    }
                )
            )
        else:
            for item, _ in group:
                item.eligible = False
                item.issues = list(dict.fromkeys([*item.issues, "identifier_conflict"]))
                output.append(item)
    return output


def check_deadline(started: float) -> None:
    if time.monotonic() - started > 60:
        raise WebError(
            503,
            "sar_prepare_timeout",
            "Dataset preparation exceeded its limit; no partial dataset was published.",
        )
