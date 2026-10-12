"""Bounded whole-trash and explicit pending/completed file-cleanup contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .dto import DTO
from .history_models import HistoryKind

HISTORY_KINDS = ("project", "job", "export", "environment_operation")
MAX_TRASH_RECORDS = 25000


class TrashPlan(DTO):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    total: int = Field(ge=0, le=MAX_TRASH_RECORDS)
    counts: dict[HistoryKind, int]
    blocked: int = Field(ge=0, le=MAX_TRASH_RECORDS)
    files_total: int = Field(default=0, ge=0, le=25000)
    bytes_total: int = Field(default=0, ge=0, le=8 * 1024**3)
    retained_targets: int = Field(default=0, ge=0)
    pending: TrashClearReceipt | None = None

    @model_validator(mode="after")
    def complete_counts(self):
        if (
            set(self.counts) != set(HISTORY_KINDS)
            or any(v < 0 for v in self.counts.values())
            or sum(self.counts.values()) != self.total
            or self.blocked > self.total
        ):
            raise ValueError("trash_counts")
        return self


class TrashClearRequest(DTO):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_total: int = Field(ge=1, le=MAX_TRASH_RECORDS, strict=True)


class TrashClearReceipt(DTO):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    plan_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleared: int = Field(ge=1, le=MAX_TRASH_RECORDS)
    counts: dict[HistoryKind, int]
    started_at: str
    completed_at: str | None = None
    status: Literal["complete", "cleanup_pending"] = "complete"
    files_total: int = Field(default=0, ge=0, le=25000)
    files_deleted: int = Field(default=0, ge=0, le=25000)
    files_retained: int = Field(default=0, ge=0, le=25000)
    bytes_removed: int = Field(default=0, ge=0, le=8 * 1024**3)
    retained_targets: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def complete_counts(self):
        if (
            set(self.counts) != set(HISTORY_KINDS)
            or any(v < 0 for v in self.counts.values())
            or sum(self.counts.values()) != self.cleared
            or self.files_deleted + self.files_retained > self.files_total
            or (self.status == "complete") != (self.completed_at is not None)
            or (
                self.status == "complete"
                and self.files_deleted + self.files_retained != self.files_total
            )
        ):
            raise ValueError("trash_counts")
        return self


TrashPlan.model_rebuild()
