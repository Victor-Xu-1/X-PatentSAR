"""Conservative retained project/checkpoint/SAR references, under the existing lease."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .errors import WebError
from .files import directory_descriptor
from .history_environment import EnvironmentHistoryStore
from .history_purge_storage import permanently_removed
from .storage import encode


@dataclass(frozen=True)
class AssetReferences:
    projects: frozenset[str]
    paths: frozenset[Path]
    digests: frozenset[str]
    sha256: str

    def protects(self, path: Path, digest: str | None = None) -> bool:
        return bool(
            digest in self.digests
            or any(parent in self.paths for parent in (path, *path.parents))
        )


def record(raw: str) -> dict:
    if not isinstance(raw, str) or len(raw.encode()) > 8 * 1024**2:
        raise WebError(
            409,
            "history_asset_reference",
            "Saved references exceed their safe bound; files were preserved.",
        )
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TypeError("reference")
        return value
    except (ValueError, TypeError, RecursionError) as error:
        raise WebError(
            409,
            "history_asset_reference",
            "Saved references could not be verified; files were preserved.",
        ) from error


def bounded_rows(connection, statement):
    rows, used = [], 0
    for row in connection.execute(statement):
        used += sum(len(value.encode()) for value in row if isinstance(value, str))
        if used > 64 * 1024**2 or len(rows) == 25000:
            raise WebError(
                413,
                "history_asset_reference",
                "The complete reference inventory exceeds its byte/row bound; files were preserved.",
            )
        rows.append(dict(row))
    return rows


def reference_path(raw) -> Path:
    if (
        not isinstance(raw, str)
        or not 1 <= len(raw) <= 4096
        or not Path(raw).is_absolute()
        or str(Path(raw)) != raw
        or "\\" in raw
        or any(ord(char) < 32 for char in raw)
        or any(part in {".", ".."} for part in raw.split("/"))
    ):
        raise WebError(
            409,
            "history_asset_reference",
            "A saved file reference is invalid; files were preserved.",
        )
    return Path(raw)


def environment_paths(store) -> set[Path]:
    """Keep configured/saved shared runtimes even in an operator-selected job path."""
    paths = {store.root / "environments/downloads"}
    with EnvironmentHistoryStore(store.root).connect() as connection:
        if connection is None:
            return paths
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"settings", "components"} <= tables:
            paths.add(
                store.root / "environments"
            )  # old unverified environment metadata
            return paths
        roots = [
            row[0] for row in connection.execute("SELECT install_root FROM settings")
        ]
        locations = []
        for row in bounded_rows(connection, "SELECT report FROM components LIMIT 9"):
            location = record(row["report"]).get("location")
            if location is not None:
                locations.append(reference_path(location))
        for row in bounded_rows(
            connection, "SELECT install_root,spec FROM operations LIMIT 25001"
        ):
            roots.append(row["install_root"])
            bindings = record(row["spec"]).get("bindings", {})
            if not isinstance(bindings, dict):
                raise WebError(
                    409,
                    "history_asset_reference",
                    "Saved environment bindings are invalid; files were preserved.",
                )
            locations.extend(
                reference_path(raw) for raw in bindings.values() if raw is not None
            )
        paths.update(reference_path(raw) for raw in roots)
        for location in locations:
            paths.add(location)
            # Venv executable bindings also depend on their sibling libraries.
            if location.parent.name == "bin":
                paths.add(location.parent.parent)
    return paths


@contextmanager
def sar_references(root: Path):
    """No SAR store construction, schema creation, migration, model or task start."""
    path = root / "sar/sar.sqlite3"
    if not os.path.lexists(path):
        yield []
        return
    descriptor = directory_descriptor(path.parent)
    try:
        info = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise WebError(
                409,
                "history_asset_reference",
                "SAR reference storage is unsafe; files were preserved.",
            )
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT metadata FROM datasets LIMIT 257"
            ).fetchall()
            if len(rows) > 256:
                raise WebError(
                    413,
                    "history_asset_reference",
                    "SAR references exceed their complete inventory bound.",
                )
            yield [record(row[0]) for row in rows]
        finally:
            connection.close()
    finally:
        os.close(descriptor)


def asset_references(
    store, connection, clearing: frozenset[tuple[str, str]]
) -> AssetReferences:
    paths, protected, digests = environment_paths(store), set(), set()
    projects = bounded_rows(
        connection, "SELECT id,sha256,run_root,pdf_rel FROM projects LIMIT 25001"
    )
    jobs = bounded_rows(connection, "SELECT id,project_id,spec FROM jobs LIMIT 25001")
    with sar_references(store.root) as datasets:
        for dataset in datasets:
            if dataset.get("source_project_id"):
                if not isinstance(dataset["source_project_id"], str):
                    raise WebError(
                        409,
                        "history_asset_reference",
                        "A SAR source reference is invalid; files were preserved.",
                    )
                protected.add(dataset["source_project_id"])
            for key in ("source_sha256", "source_document_sha256"):
                if isinstance(dataset.get(key), str):
                    digests.add(dataset[key])
    for project in projects:
        identifier = project["id"]
        if ("project", identifier) not in clearing and not permanently_removed(
            connection, "project", identifier
        ):
            protected.add(identifier)
        if identifier in protected:
            if project["sha256"]:
                digests.add(project["sha256"])
            if project["run_root"]:
                paths.add(reference_path(project["run_root"]))
            if project["pdf_rel"]:
                raw = Path(project["pdf_rel"])
                paths.add(
                    reference_path(str(raw if raw.is_absolute() else store.root / raw))
                )
    # Retained checkpoint descendants can refer to removed ancestors. Protect
    # their exact paths; every visible parent also owns its historical attempts.
    indexed = {row["id"]: row for row in jobs}
    pending = [
        row["id"]
        for row in jobs
        if row["project_id"] in protected
        or (
            ("job", row["id"]) not in clearing
            and not permanently_removed(connection, "job", row["id"], row["project_id"])
        )
    ]
    seen = set()
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        row = indexed.get(identifier)
        if row is None:
            raise WebError(
                409,
                "history_asset_reference",
                "Checkpoint ancestry is missing; files were preserved.",
            )
        spec = record(row["spec"])
        for key in ("output_dir", "pdf_path", "source_ocr_cache"):
            if spec.get(key) not in (None, ""):
                paths.add(reference_path(spec[key]))
        for key in ("checkpoint_source_job_id", "resume_job_id"):
            if spec.get(key):
                if not isinstance(spec[key], str):
                    raise WebError(
                        409,
                        "history_asset_reference",
                        "Checkpoint ancestry is invalid; files were preserved.",
                    )
                pending.append(spec[key])
    fingerprint = hashlib.sha256(
        encode([sorted(protected), sorted(map(str, paths)), sorted(digests)]).encode()
    ).hexdigest()
    return AssetReferences(
        frozenset(protected), frozenset(paths), frozenset(digests), fingerprint
    )
