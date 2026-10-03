"""Read-only API-v1 focus selection, never an editable source coordinate."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .dto import DTO

ActivitySourceKey = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", strict=True)]


class ActivityFocus(DTO):
    compound_id: str = Field(min_length=1, max_length=200)
    activity_key: ActivitySourceKey
    status: Literal["located", "page_only"]
    boxes: list[list[float]] = Field(max_length=80)
    message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_boxes(self) -> ActivityFocus:
        if (self.status == "located") != bool(self.boxes):
            raise ValueError("Located focus requires actual geometry")
        for box in self.boxes:
            if (
                len(box) != 4
                or not all(math.isfinite(v) and v >= 0 for v in box)
                or box[2] <= box[0]
                or box[3] <= box[1]
            ):
                raise ValueError("Invalid focus geometry")
        return self
