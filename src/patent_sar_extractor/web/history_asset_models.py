"""Private bounded file-cleanup inventory; never a recursive delete instruction."""

from __future__ import annotations

import re

from pydantic import Field

from .dto import DTO

MAX_CLEANUP_FILES = 25000
MAX_CLEANUP_BYTES = 8 * 1024**3
UPLOAD_FILE = re.compile(r"(?:upload|original)-[a-z0-9_]{8}\.pdf")


class CleanupFile(DTO):
    path: str = Field(min_length=1, max_length=4096)
    anchor: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    identity: tuple[int, int, int, int, int, int]


class CleanupDirectory(DTO):
    path: str = Field(min_length=1, max_length=4096)
    anchor: str = Field(min_length=1, max_length=4096)
    identity: tuple[int, int]


class CleanupManifest(DTO):
    files: list[CleanupFile] = Field(default_factory=list, max_length=MAX_CLEANUP_FILES)
    directories: list[CleanupDirectory] = Field(
        default_factory=list, max_length=MAX_CLEANUP_FILES
    )
    retained_targets: int = Field(default=0, ge=0)
    references_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def size_bytes(self) -> int:
        return sum(item.identity[2] for item in self.files)
