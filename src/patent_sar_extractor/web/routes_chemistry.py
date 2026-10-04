"""One cheap authenticated MDL conversion adapter; no model or persistence."""

from fastapi import APIRouter
from pydantic import Field, field_validator

from .correction_chemistry import (
    MAX_MOLFILE_BYTES,
    converted_smiles,
    validate_molfile_text,
)
from .dto import DTO
from .errors import WebError


class StructureInput(DTO):
    molfile: str = Field(min_length=1, max_length=MAX_MOLFILE_BYTES, strict=True)

    @field_validator("molfile")
    @classmethod
    def validate_mdl(cls, value: str) -> str:
        validate_molfile_text(value)
        return value


class StructureConversion(DTO):
    smiles: str | None = Field(max_length=2048)


def chemistry_routes() -> APIRouter:
    router = APIRouter(prefix="/api/v1/chemistry")

    @router.post("/structure", response_model=StructureConversion)
    def structure(body: StructureInput) -> StructureConversion:
        try:
            return StructureConversion(smiles=converted_smiles(body.molfile))
        except ValueError as exc:
            raise WebError(
                422,
                "structure_conversion_invalid",
                "结构无效或包含暂不支持的立体化学，未接受修改。",
            ) from exc

    return router
