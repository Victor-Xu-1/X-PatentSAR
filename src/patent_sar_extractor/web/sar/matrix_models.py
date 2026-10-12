"""Bounded read-view contract; immutable scientific DTOs/epochs are untouched."""

from pydantic import Field, model_validator

from ..dto import DTO
from .preview_models import PreviewMoleculeDrawing, StudyPreview


class StudyMatrix(DTO):
    reference_drawing: PreviewMoleculeDrawing
    previews: list[StudyPreview] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def common_source(self):
        first = self.previews[0]
        if (
            self.reference_drawing.id != first.reference.molecule_id
            or any(
                item.job != first.job
                or item.reference != first.reference
                or item.drawings is None
                for item in self.previews
            )
            or len({item.candidate.molecule_id for item in self.previews})
            != len(self.previews)
        ):
            raise ValueError("matrix_source_identity")
        return self
