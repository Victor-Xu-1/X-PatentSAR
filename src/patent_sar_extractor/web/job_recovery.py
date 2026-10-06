"""Preserve a verified process-cleanup receipt before making a task resumable."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import WebError
from .files import SafeFiles, private_directory
from .process_identity import (
    MAX_IDENTITY_BYTES,
    previous_kernel_boot,
    validate_identity,
)
from .processes import ProcessIdentity, ProcessRunner
from .storage import Store, encode, now

SCHEMA = {"name": "patentsar.process-recovery", "version": 1}


def decode_identity(raw: str) -> ProcessIdentity:
    if not isinstance(raw, str) or len(raw.encode()) > MAX_IDENTITY_BYTES:
        raise ValueError("Process identity exceeds its bound")
    return ProcessIdentity(**validate_identity(json.loads(raw)))


def preserve_cleanup(
    store: Store, row: dict[str, Any], identity: ProcessIdentity, runner: ProcessRunner
) -> None:
    raw = row["identity"]
    digest = hashlib.sha256(raw.encode()).hexdigest()
    directory = private_directory(store.root / "job-recovery")
    filename = f"{row['id']}-{digest}.json"
    data = {
        "schema": SCHEMA,
        "job_id": row["id"],
        "project_id": row["project_id"],
        "spec_sha256": hashlib.sha256(row["spec"].encode()).hexdigest(),
        "identity_sha256": digest,
        "identity": identity.to_dict(),
        "current_boot_id": getattr(runner, "boot_id", None),
        "reason": "previous_kernel_boot"
        if previous_kernel_boot(identity.boot_id, getattr(runner, "boot_id", None))
        else "verified_cleanup",
        "verified_at": now(),
    }
    destination = directory / filename
    if destination.exists() or destination.is_symlink():
        existing = json.loads(
            SafeFiles(directory).read(filename, max_bytes=MAX_IDENTITY_BYTES * 2)
        )
        if not isinstance(existing, dict) or any(
            encode(existing.get(key)) != encode(data[key])
            for key in (
                "schema",
                "job_id",
                "project_id",
                "spec_sha256",
                "identity_sha256",
                "identity",
            )
        ):
            raise WebError(
                409,
                "recovery_evidence_changed",
                "Existing recovery evidence is invalid; no task record was cleared.",
            )
        return
    payload = encode(data).encode()
    if len(payload) > MAX_IDENTITY_BYTES * 2:
        raise ValueError("Recovery evidence exceeds its bound")
    fd, temporary = tempfile.mkstemp(prefix=".recovery-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish without replacing any existing receipt, even after a race.
        os.link(temporary, destination, follow_symlinks=False)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)  # Only this writer's own temporary.


def release_retained_identity(store: Store, row: dict[str, Any]) -> None:
    """CAS only recovery metadata; old stage history/finish time/outputs stay exact."""
    with store.connect(write=True) as connection:
        connection.execute(
            "UPDATE jobs SET identity=NULL,error=? WHERE id=? AND status='interrupted' AND identity=? AND spec=?",
            (
                encode(
                    {
                        "code": "server_interrupted",
                        "message": "Previous process safely reconciled; verified checkpoints can be resumed.",
                    }
                ),
                row["id"],
                row["identity"],
                row["spec"],
            ),
        )
