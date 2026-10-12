"""Durable finite cleanup on explicit clear/resume; reads never repeat deletion."""

from __future__ import annotations

import hashlib
import time

from .errors import WebError
from .history_asset_models import CleanupManifest
from .history_asset_references import asset_references
from .history_asset_removal import remove_empty_directory, remove_file
from .history_purge_models import TrashClearReceipt
from .storage import encode, now


def pending_receipt(store) -> TrashClearReceipt | None:
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT payload FROM history_purge_requests WHERE json_extract(payload,'$.status')='cleanup_pending' ORDER BY rowid LIMIT 2"
        ).fetchall()
    if len(rows) > 1:
        raise WebError(
            409,
            "history_cleanup_manifest",
            "Multiple unfinished clear requests require reconciliation; files were preserved.",
        )
    return TrashClearReceipt.model_validate_json(rows[0][0]) if rows else None


def prepare_cleanup(connection, request_id: str, manifest: CleanupManifest) -> None:
    payload = manifest.model_dump_json()
    connection.execute(
        "INSERT INTO history_file_cleanup(request_id,manifest,sha256,next_index) VALUES(?,?,?,0)",
        (request_id, payload, hashlib.sha256(payload.encode()).hexdigest()),
    )


def continue_cleanup(store, request_id: str) -> TrashClearReceipt:
    with store.connect() as connection:
        saved = connection.execute(
            "SELECT * FROM history_file_cleanup WHERE request_id=?", (request_id,)
        ).fetchone()
        raw = connection.execute(
            "SELECT payload FROM history_purge_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
        references = asset_references(store, connection, frozenset())
    receipt = TrashClearReceipt.model_validate_json(raw[0])
    if receipt.status == "complete":
        return receipt
    if (
        saved is None
        or hashlib.sha256(saved["manifest"].encode()).hexdigest() != saved["sha256"]
    ):
        raise WebError(
            409,
            "history_cleanup_manifest",
            "The retained cleanup inventory could not be verified; no file was deleted.",
        )
    manifest = CleanupManifest.model_validate_json(saved["manifest"])
    cursor = saved["next_index"]
    directory_cursor = saved["next_directory"]
    if (
        not 0 <= cursor <= len(manifest.files)
        or not 0 <= directory_cursor <= len(manifest.directories)
        or receipt.files_total != len(manifest.files)
        or cursor != receipt.files_deleted + receipt.files_retained
    ):
        raise WebError(
            409,
            "history_cleanup_manifest",
            "Cleanup progress differs from its sealed inventory; no file was deleted.",
        )
    started = time.monotonic()
    try:
        for index in range(cursor, len(manifest.files)):
            if time.monotonic() - started > 30:
                break  # finite request; the same explicit request resumes next chunk
            item = manifest.files[index]
            removed = remove_file(
                store, item, request_id, index, references, deadline=started + 30
            )
            receipt.files_deleted += int(removed)
            receipt.files_retained += int(not removed)
            receipt.bytes_removed += item.identity[2] if removed else 0
            cursor = index + 1
            if cursor % 16 == 0:
                _progress(store, request_id, receipt, cursor, directory_cursor)
        if cursor == len(manifest.files):
            _progress(store, request_id, receipt, cursor, directory_cursor)
            directories = sorted(
                manifest.directories, key=lambda item: len(item.path), reverse=True
            )
            for index in range(directory_cursor, len(directories)):
                if time.monotonic() - started > 30:
                    break
                directory = directories[index]
                remove_empty_directory(store, directory, references)
                directory_cursor = index + 1
                if directory_cursor % 16 == 0:
                    _progress(store, request_id, receipt, cursor, directory_cursor)
            if directory_cursor == len(directories):
                receipt.status = "complete"
                receipt.completed_at = now()
    except (OSError, ValueError, WebError):
        # Publish only completed exact-file work, never fake whole-operation success.
        _progress(store, request_id, receipt, cursor, directory_cursor)
        return receipt
    _progress(store, request_id, receipt, cursor, directory_cursor)
    return receipt


def _progress(store, request_id, receipt, cursor, directory_cursor):
    with store.connect(write=True) as connection:
        connection.execute(
            "UPDATE history_file_cleanup SET next_index=?,next_directory=? WHERE request_id=?",
            (cursor, directory_cursor, request_id),
        )
        connection.execute(
            "UPDATE history_purge_requests SET payload=? WHERE request_id=?",
            (encode(receipt.model_dump()), request_id),
        )
