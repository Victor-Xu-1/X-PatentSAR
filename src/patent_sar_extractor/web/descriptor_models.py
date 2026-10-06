"""Source-bound calculation evidence, never a substitute for model acceptance."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .descriptor_fields import DESCRIPTOR_KEYS, descriptor_engine
from .dto import DTO, Error
from .prediction_models import PredictionMetric


class DescriptorEngine(DTO):
    name: Literal["RDKit"]
    version: str = Field(min_length=1, max_length=40)
    algorithm_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def current_algorithm(self) -> DescriptorEngine:
        if self.model_dump() != descriptor_engine():
            raise ValueError(
                "Descriptor engine is not the current calculation authority"
            )
        return self


class DescriptorSummary(DTO):
    status: Literal[
        "not_run", "pending", "running", "complete", "failed", "stale", "unavailable"
    ] = "not_run"
    properties: list[PredictionMetric] = Field(default_factory=list, max_length=5)
    source_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    smiles_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    engine: DescriptorEngine | None = None
    generated_at: str | None = Field(default=None, max_length=100)
    job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    error: Error | None = None
    review_only: Literal[True] = True

    @field_validator("generated_at")
    @classmethod
    def timestamp(cls, value: str | None) -> str | None:
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Calculation timestamp must identify its timezone")
        return value

    @model_validator(mode="after")
    def complete_observation(self) -> DescriptorSummary:
        if self.status == "complete":
            if (
                tuple(v.key for v in self.properties) != DESCRIPTOR_KEYS
                or not self.source_fingerprint
                or not self.smiles_sha256
                or self.engine is None
                or not self.generated_at
                or not self.job_id
                or self.error is not None
            ):
                raise ValueError(
                    "Complete calculations require five source-bound observations"
                )
        elif (
            self.properties or self.engine is not None or self.generated_at is not None
        ):
            raise ValueError(
                "Incomplete calculations cannot expose old numeric evidence"
            )
        if self.status in {"pending", "running", "complete"} and (
            not self.source_fingerprint or not self.smiles_sha256 or not self.job_id
        ):
            raise ValueError("Calculations require source and producer identity")
        if self.status == "failed" and self.error is None:
            raise ValueError("Failed calculations require an explicit error")
        if self.error and (
            len(self.error.code) > 100 or len(self.error.message) > 2000
        ):
            raise ValueError("Calculation error exceeds its limit")
        return self
