"""Additive review-only molecular analysis DTOs, not pipeline artifacts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictStr, model_validator

from .models import DTO, Acceptance

BoundedSMILES = Annotated[StrictStr, Field(min_length=1, max_length=2048)]


class ADMETRequest(DTO):
    smiles: list[BoundedSMILES] = Field(min_length=1, max_length=50)


class RecognitionRequest(DTO):
    """An explicitly empty object: clients cannot supply paths or model settings."""


class AnalysisEngine(DTO):
    name: str = Field(min_length=1, max_length=40)
    version: str = Field(min_length=1, max_length=40)


class ADMETEngine(AnalysisEngine):
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Property(DTO):
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    value: float = Field(strict=True)
    unit: str = Field(min_length=1, max_length=100)
    kind: Literal["descriptor", "prediction"]


class Prediction(DTO):
    smiles: BoundedSMILES
    properties: list[Property] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_properties(self) -> Prediction:
        if len({p.key for p in self.properties}) != len(self.properties):
            raise ValueError("Duplicate property keys")
        return self


class ADMETResponse(DTO):
    engine: ADMETEngine
    generated_at: str
    review_only: Literal[True] = True
    predictions: list[Prediction] = Field(min_length=1, max_length=50)
    warnings: list[str] = Field(max_length=100)


class RecognitionResponse(DTO):
    compound_id: str
    status: Literal["recognized", "rejected"]
    smiles: BoundedSMILES | None
    engine: AnalysisEngine
    warnings: list[str] = Field(max_length=100)
    review_only: Literal[True] = True

    @model_validator(mode="after")
    def consistent_status(self) -> RecognitionResponse:
        if (self.status == "recognized") != (self.smiles is not None):
            raise ValueError("Recognition status and SMILES disagree")
        return self


class EvidenceCounts(DTO):
    structures: int = Field(ge=0)
    activity_rows: int = Field(ge=0)
    compounds: int = Field(ge=0)
    smiles: int = Field(ge=0)
    source_located: int = Field(ge=0)
    needs_review: int = Field(ge=0)


class ActivityEvidence(DTO):
    name: str
    unit: str | None
    rows: int = Field(ge=0)
    numeric_rows: int = Field(ge=0)
    min: float | None
    max: float | None
    censored_rows: int = Field(ge=0)
    target: str | None


class TargetEvidence(DTO):
    name: str
    rows: int = Field(ge=0)


class EvidenceSummary(DTO):
    project_id: str
    generated_at: str
    acceptance: Acceptance
    counts: EvidenceCounts
    activities: list[ActivityEvidence]
    targets: list[TargetEvidence]
    limitations: list[str]
    source_pages: list[int]
