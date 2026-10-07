"""Additive bounded presentation of actual source-stereo observations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .dto import DTO


class StereoEvidence(DTO):
    # Legacy observations remain readable, but only the current epoch can pass
    # the separate formal source gate. Presentation never refreshes old proof.
    version: Literal[1, 2]
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    image_size: list[int] = Field(min_length=2, max_length=2)
    unknown_bond_boxes: list[list[float]] = Field(max_length=64)
    status: Literal["no_unknown_detected", "unknown_preserved", "conflict", "ambiguous"]
    reason: str = Field(max_length=512)
    assigned_centers: int = Field(ge=0, le=512, strict=True)
    unassigned_centers: int = Field(ge=0, le=512, strict=True)
    assigned_double_bonds: int = Field(ge=0, le=768, strict=True)
    absolute_configuration_verified: Literal[False]
