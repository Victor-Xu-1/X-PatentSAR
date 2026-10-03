"""Source-bound six-metric presentation, separate from formal extraction QA."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from patent_sar_extractor.workers.analysis_protocol import (
    ADMET_BUNDLE_SHA256,
    ADMET_VERSION,
)

from .dto import DTO, Error

MetricKey = Literal[
    "molecular_weight",
    "logP",
    "tpsa",
    "hydrogen_bond_donors",
    "hydrogen_bond_acceptors",
    "Solubility_AqSolDB",
]
METRIC_KEYS: tuple[MetricKey, ...] = (
    "molecular_weight",
    "logP",
    "tpsa",
    "hydrogen_bond_donors",
    "hydrogen_bond_acceptors",
    "Solubility_AqSolDB",
)
METRIC_SPECS = {
    "molecular_weight": ("MW", "Dalton", "descriptor"),
    "logP": ("LogP", "log-ratio", "descriptor"),
    "tpsa": ("TPSA", "Å^2", "descriptor"),
    "hydrogen_bond_donors": ("HBD", "#", "descriptor"),
    "hydrogen_bond_acceptors": ("HBA", "#", "descriptor"),
    "Solubility_AqSolDB": ("LogS", "log(mol/L)", "prediction"),
}


class PredictionMetric(DTO):
    key: MetricKey
    label: str = Field(min_length=1, max_length=200)
    value: float = Field(strict=True)
    unit: str = Field(min_length=1, max_length=100)
    kind: Literal["descriptor", "prediction"]

    @model_validator(mode="after")
    def reviewed_metadata(self) -> PredictionMetric:
        label, unit, kind = METRIC_SPECS[self.key]
        if (self.label, self.unit, self.kind) != (label, unit, kind):
            raise ValueError("Prediction metadata differs from the reviewed catalog")
        if (
            self.key
            in {
                "molecular_weight",
                "tpsa",
                "hydrogen_bond_donors",
                "hydrogen_bond_acceptors",
            }
            and self.value < 0
        ):
            raise ValueError("Computed descriptor is negative")
        if (
            self.key in {"hydrogen_bond_donors", "hydrogen_bond_acceptors"}
            and not self.value.is_integer()
        ):
            raise ValueError("Hydrogen-bond counts must be integers")
        return self


class PredictionEngine(DTO):
    name: str = Field(min_length=1, max_length=40)
    version: str = Field(min_length=1, max_length=40)
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def pinned_producer(self) -> PredictionEngine:
        if (self.name, self.version, self.model_sha256) != (
            "ADMET-AI",
            ADMET_VERSION,
            ADMET_BUNDLE_SHA256,
        ):
            raise ValueError("Prediction engine is not the verified pinned producer")
        return self


class PredictionSummary(DTO):
    status: Literal[
        "not_run", "pending", "running", "complete", "failed", "stale", "unavailable"
    ] = "not_run"
    properties: list[PredictionMetric] = Field(default_factory=list, max_length=6)
    source_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    smiles_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    engine: PredictionEngine | None = None
    generated_at: str | None = Field(default=None, max_length=100)
    job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    warnings: list[str] = Field(default_factory=list, max_length=100)
    error: Error | None = None
    review_only: Literal[True] = True

    @field_validator("generated_at")
    @classmethod
    def timestamp(cls, value: str | None) -> str | None:
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Prediction timestamp must identify its timezone")
        return value

    @field_validator("warnings")
    @classmethod
    def bounded_warnings(cls, values: list[str]) -> list[str]:
        if any(
            len(value) > 2000 or any(ord(c) < 32 and c not in "\t\n\r" for c in value)
            for value in values
        ):
            raise ValueError("Prediction warnings are invalid or over their limit")
        return values

    @model_validator(mode="after")
    def complete_observation(self) -> PredictionSummary:
        if self.status == "complete":
            if (
                tuple(metric.key for metric in self.properties) != METRIC_KEYS
                or not self.source_fingerprint
                or not self.smiles_sha256
                or self.engine is None
                or not self.generated_at
                or not self.job_id
                or self.error is not None
            ):
                raise ValueError(
                    "A completed prediction requires six source-bound observations"
                )
        elif self.properties:
            raise ValueError(
                "Unavailable or stale predictions must not expose old values"
            )
        if self.status in {"pending", "running", "complete"} and (
            not self.source_fingerprint or not self.smiles_sha256 or not self.job_id
        ):
            raise ValueError("Producer observations must identify their source and job")
        if self.status != "complete" and (
            self.engine is not None or self.generated_at is not None
        ):
            raise ValueError(
                "Incomplete predictions cannot carry completed model evidence"
            )
        if self.status == "failed" and self.error is None:
            raise ValueError("Failed predictions require an explicit error")
        if self.error is not None and (
            len(self.error.code) > 100 or len(self.error.message) > 2000
        ):
            raise ValueError("Prediction error exceeds its limit")
        return self
