"""Current write destinations and immutable historical file-root resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .data_location_policy import DataLocationPolicy
from .errors import WebError
from .files import SafeFiles
from .location_records import read_locations


class WorkspaceLocations:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.policy = DataLocationPolicy.from_environment(state_root)

    def roots(self, kind: str) -> tuple[Path, ...]:
        return tuple(
            Path(raw)
            for name, raw in read_locations(self.state_root).roots
            if name == kind
        )

    def upload_root(self) -> Path:
        record = read_locations(self.state_root)
        return self.policy.prepare("uploads", record.upload_root)

    def result_root(self) -> Path:
        record = read_locations(self.state_root)
        return self.policy.prepare("results", record.result_root)

    def pdf_record(self, path: Path) -> str:
        if path.parent not in self.roots("uploads") or path.name in {"", ".", ".."}:
            raise WebError(
                409,
                "storage_original",
                "Uploaded original does not belong to a recorded upload location.",
            )
        self.policy.validate("uploads", str(path.parent))
        return (
            str(path.relative_to(self.state_root))
            if path.is_relative_to(self.state_root)
            else str(path)
        )

    def pdf_files(self, project: dict[str, Any]) -> tuple[SafeFiles, str]:
        raw = project.get("pdf_rel")
        if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
            raise WebError(409, "storage_original", "Original PDF path is invalid.")
        path = Path(raw)
        if path.is_absolute():
            if str(path) != raw or path.parent not in self.roots("uploads"):
                raise WebError(
                    409,
                    "storage_original",
                    "Original PDF is outside recorded upload locations.",
                )
            self.policy.validate("uploads", str(path.parent))
            return SafeFiles(path.parent), path.name
        if (
            len(path.parts) != 2
            or path.parts[0] != "uploads"
            or any(part in {".", ".."} for part in raw.split("/"))
        ):
            raise WebError(
                409,
                "storage_original",
                "Legacy original must belong to this workspace's upload directory.",
            )
        return SafeFiles(self.state_root), raw

    def pdf_path(self, project: dict[str, Any]) -> Path:
        files, relative = self.pdf_files(project)
        return files.root / relative

    def result_anchor(self, path: Path) -> Path:
        for root in self.roots("results"):
            if path.is_relative_to(root) and path != root:
                return self.policy.validate("results", str(root))
        raise WebError(
            409, "storage_output", "Output is outside recorded result locations."
        )
