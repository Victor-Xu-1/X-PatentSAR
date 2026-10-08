"""Non-destructive private v1 upgrade and verified legacy input recovery."""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

from ..errors import WebError
from .assets import digest
from .models import SARJob


def migrate_v1(connection: sqlite3.Connection, root: Path) -> bool:
    backup = root / ("sar-v1-backup-" + uuid.uuid4().hex + ".sqlite3")
    descriptor = os.open(
        backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    os.close(descriptor)
    with sqlite3.connect(backup) as target:
        connection.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise WebError(
                409,
                "sar_migration",
                "Legacy SAR backup integrity could not be verified.",
            )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
    if "id" not in columns:
        raise WebError(409, "sar_migration", "Legacy SAR job schema is unavailable.")
    missing_ready = "ready" not in columns
    if missing_ready:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN ready INTEGER NOT NULL DEFAULT 0"
        )
    if "cleanup_verified" not in columns:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN cleanup_verified INTEGER NOT NULL DEFAULT 0"
        )
    return missing_ready


def recover_legacy_inputs(store, assets) -> None:
    if not store.migrated_ready:
        return
    with store.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute("SELECT * FROM jobs WHERE deleted=0")
        ]
    for row in rows:
        value = SARJob.model_validate_json(row["payload"])
        try:
            packet = assets.job_files(row["root"], value.id).json(
                "input.json", optional=False
            )
            valid = (
                isinstance(packet, dict)
                and packet.get("schema") == 1
                and packet.get("job_id") == value.id
                and digest(packet) == value.input_sha256
            )
        except (WebError, OSError, ValueError):
            valid = False
        # Legacy queued jobs require explicit resume after their inputs are verified.
        if value.status == "queued":
            value.status = "interrupted" if valid else "failed"
        if not valid:
            value.error_code = "sar_input_unpublished"
            value.error_message = (
                "Legacy SAR input could not be verified; retained for review."
            )
        with store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET ready=?,status=?,payload=? WHERE id=?",
                (int(valid), value.status, value.model_dump_json(), value.id),
            )


def recover_preparing_uploads(store) -> None:
    # Called only after the application's exclusive workspace owner is acquired.
    # Retain original bytes/SHA/retention counts; free only abandoned pending slots.
    with store.connect(write=True) as connection:
        connection.execute(
            "UPDATE uploads SET status='failed' WHERE status='preparing'"
        )
