"""Recoverable history removal; separate from immutable scientific evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

HistoryKind = Literal["project", "job", "export", "environment_operation"]


class HistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: HistoryKind
    id: str = Field(min_length=1, max_length=64)
    project_id: str | None = Field(default=None, max_length=32)
    title: str = Field(min_length=1, max_length=250)
    status: str = Field(max_length=40)
    created_at: str = Field(max_length=80)
    deleted_at: str | None = Field(default=None, max_length=80)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    can_delete: StrictBool
    can_restore: StrictBool
    blocked_reason: str | None = Field(default=None, max_length=300)
    size_bytes: int | None = Field(default=None, ge=0)


class HistoryList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HistoryEntry] = Field(max_length=100)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class HistoryMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
