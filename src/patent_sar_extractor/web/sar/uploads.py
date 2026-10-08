"""SHA-bound CSV preview originals in the selected upload location."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from ..errors import WebError
from .assets import SARAssets, atomic_bytes
from .csv_reader import MAX_CSV_BYTES, preview
from .models import CSVPreview
from .store import SARStore


class Uploads:
    def __init__(self, store: SARStore, assets: SARAssets):
        self.store, self.assets = store, assets

    def create(self, data: bytes, filename: str) -> CSVPreview:
        if not 1 <= len(filename) <= 200 or any(
            char in filename for char in "/\\\x00\r\n"
        ):
            raise WebError(422, "sar_csv_filename", "CSV filename is invalid.")
        token = uuid.uuid4().hex
        value = preview(data, filename, token)
        root = self.assets.area("uploads")
        with self.store.connect(write=True) as connection:
            count, size = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(size),0) FROM uploads"
            ).fetchone()
            pending = connection.execute(
                "SELECT COUNT(*) FROM uploads WHERE status IN ('preparing','ready')"
            ).fetchone()[0]
            if count >= 1024 or pending >= 32 or size + len(data) > 512 * 1024 * 1024:
                raise WebError(
                    413,
                    "sar_upload_limit",
                    "SAR CSV staging/retention limit has been reached.",
                )
            # Reserve every retention quota atomically BEFORE writing bytes.
            # An interrupted write remains counted rather than an orphan bypass.
            connection.execute(
                "INSERT INTO uploads VALUES(?,?,?,?,?,?,'preparing')",
                (
                    token,
                    filename,
                    str(root),
                    hashlib.sha256(data).hexdigest(),
                    len(data),
                    value.model_dump_json(),
                ),
            )
        try:
            atomic_bytes(root, token + ".csv", data)
        except (WebError, OSError, ValueError):
            with self.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE uploads SET status='failed' WHERE token=?", (token,)
                )
            raise
        with self.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE uploads SET status='ready' WHERE token=? AND status='preparing'",
                (token,),
            )
        return value

    def read(self, token: str) -> tuple[bytes, str]:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM uploads WHERE token=? AND status IN ('ready','used')",
                (token,),
            ).fetchone()
        if row is None:
            raise WebError(
                404, "sar_csv_missing", "CSV preview is no longer available."
            )
        data = self.assets.validate(Path(row["root"]), "uploads").read(
            token + ".csv", max_bytes=MAX_CSV_BYTES
        )
        if (
            hashlib.sha256(data).hexdigest() != row["sha256"]
            or len(data) != row["size"]
        ):
            raise WebError(
                409, "sar_csv_changed", "CSV changed since preview; import was refused."
            )
        return data, row["sha256"]

    def used(self, token: str) -> None:
        with self.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE uploads SET status='used' WHERE token=? AND status='ready'",
                (token,),
            )

    def remove(self, token: str) -> None:
        with self.store.connect(write=True) as connection:
            row = connection.execute(
                "SELECT status FROM uploads WHERE token=?", (token,)
            ).fetchone()
            if row is None:
                raise WebError(404, "sar_csv_missing", "CSV preview is unavailable.")
            if row[0] == "used":
                raise WebError(
                    409,
                    "sar_csv_retained",
                    "Imported source CSV is retained with its dataset.",
                )
            if row[0] == "preparing":
                raise WebError(
                    409, "sar_csv_preparing", "CSV publication is still active."
                )
            connection.execute(
                "UPDATE uploads SET status='removed' WHERE token=?", (token,)
            )
