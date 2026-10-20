"""Bounded receipt-bound passive drawing transport, not a scientific result cache."""

from typing import Literal

from pydantic import Field, model_validator

from ..models import DTO
from .models import SARJob
from .study_models import StudyDrawing

MAX_DRAWING_BATCH = 32
StudyDrawingKind = Literal["molecule", "scaffold", "fragment"]


class StudyDrawingError(DTO):
    status: Literal[404, 422]
    code: str
    message: str


class StudyDrawingEntry(DTO):
    identifier: str
    result: StudyDrawing | None = None
    error: StudyDrawingError | None = None

    @model_validator(mode="after")
    def complete_entry(self):
        if (self.result is None) == (self.error is None) or (
            self.result is not None and self.result.id != self.identifier
        ):
            raise ValueError(
                "A drawing entry needs exactly one matching result or failure"
            )
        return self


class StudyDrawingBatch(DTO):
    job: SARJob
    kind: StudyDrawingKind
    region_id: str
    items: list[StudyDrawingEntry] = Field(min_length=1, max_length=MAX_DRAWING_BATCH)
