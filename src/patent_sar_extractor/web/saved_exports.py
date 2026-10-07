"""Persist the existing export iterator once, in the current managed result root."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .errors import WebError
from .files import SafeFiles, directory_descriptor, private_directory
from .history_storage import ensure_project_visible, tombstone
from .storage import Store, now

MAX_EXPORT_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class SavedExport:
    path: Path
    sha256: str
    size: int
    store: Store | None = None


def save_export(
    store: Store, project_id: str, format: str, chunks: Iterable[bytes]
) -> SavedExport:
    if (
        format not in {"csv", "json"}
        or len(project_id) != 32
        or any(char not in "0123456789abcdef" for char in project_id)
    ):
        raise WebError(400, "export_location", "Export identity or format is invalid.")
    temporary: str | None = None
    store.project(project_id)
    digest = hashlib.sha256()
    total = 0
    try:
        root = private_directory(store.locations.result_root() / project_id / "exports")
        destination = root / (uuid.uuid4().hex + "." + format)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".export-", suffix=".pending", dir=root
        )
        with os.fdopen(descriptor, "wb") as output:
            for content in chunks:
                total += len(content)
                if total > MAX_EXPORT_BYTES:
                    raise WebError(
                        413,
                        "export_limit",
                        "Generated export exceeds the supported file size.",
                    )
                output.write(content)
                digest.update(content)
            output.flush()
            os.fsync(output.fileno())
        from .history_exports import register_export

        with store.connect(write=True) as connection:
            ensure_project_visible(connection, project_id)
            os.link(temporary, destination, follow_symlinks=False)
            register_export(connection, project_id, destination, now())
            root_fd = directory_descriptor(root)
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
    except OSError as error:
        raise WebError(
            409,
            "export_storage",
            "Export could not be saved to the selected result directory.",
        ) from error
    finally:
        if temporary is not None:
            Path(temporary).unlink(
                missing_ok=True
            )  # Only this exclusive newly generated file.
    return SavedExport(destination, digest.hexdigest(), total, store)


def export_bytes(saved: SavedExport) -> Iterator[bytes]:
    """Authorize before response headers; an authorized in-flight stream can finish."""
    from .history_exports import export_id

    if saved.store is not None:
        with saved.store.connect() as connection:
            connection.execute("BEGIN")
            ensure_project_visible(connection, saved.path.parent.parent.name)
            if (
                tombstone(connection, "export", export_id(saved.path))["deleted_at"]
                is not None
            ):
                raise WebError(
                    404, "history_export_missing", "Export is in the recoverable trash."
                )

    def chunks() -> Iterator[bytes]:
        with SafeFiles(saved.path.parent).open(
            saved.path.name, max_bytes=MAX_EXPORT_BYTES
        ) as source:
            while chunk := source.read(64 * 1024):
                yield chunk

    return chunks()
