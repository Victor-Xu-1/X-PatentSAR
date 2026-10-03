"""One finite, strict DTO boundary shared by independent Web response models."""

from pydantic import BaseModel, ConfigDict


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Error(DTO):
    code: str
    message: str
