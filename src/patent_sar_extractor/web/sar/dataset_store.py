"""Atomic complete dataset publication, bounded pages and recoverable removal."""

from __future__ import annotations

from ..errors import WebError
from .input_records import MAX_DATASET_BYTES
from .models import Dataset, DatasetList, Molecule, MoleculePage, Region
from .store import SARStore, dataset_row


class Datasets:
    def __init__(self, store: SARStore):
        self.store = store

    def existing(self, request_id: str, request_sha256: str) -> Dataset | None:
        with self.store.connect() as connection:
            return self._existing(connection, request_id, request_sha256)

    @staticmethod
    def _existing(connection, request_id: str, request_sha256: str) -> Dataset | None:
        row = connection.execute(
            "SELECT * FROM datasets WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256 or row["deleted"]:
            raise WebError(
                409,
                "sar_request_conflict",
                "This request identity belongs to different or removed data.",
            )
        return Dataset.model_validate_json(row["metadata"])

    def publish(
        self,
        dataset: Dataset,
        molecules: list[Molecule],
        request_id: str,
        request_sha256: str,
        source_revision: str | None = None,
    ) -> Dataset:
        payloads = [value.model_dump_json() for value in molecules]
        if (
            len(molecules) > 25000
            or sum(len(value.encode()) for value in payloads) > MAX_DATASET_BYTES
        ):
            raise WebError(
                413,
                "sar_dataset_limit",
                "SAR dataset exceeds its limit; no partial dataset was published.",
            )
        with self.store.connect(write=True) as connection:
            previous = self._existing(connection, request_id, request_sha256)
            if previous:
                return previous
            if connection.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] >= 256:
                raise WebError(
                    413,
                    "sar_dataset_limit",
                    "SAR dataset retention limit has been reached.",
                )
            connection.execute(
                "INSERT INTO datasets VALUES(?,?,?,?,?,0)",
                (
                    dataset.id,
                    request_id,
                    request_sha256,
                    dataset.model_dump_json(),
                    source_revision,
                ),
            )
            connection.executemany(
                "INSERT INTO molecules VALUES(?,?,?,?,?)",
                [
                    (dataset.id, item.id, ordinal, item.label, payload)
                    for ordinal, (item, payload) in enumerate(
                        zip(molecules, payloads, strict=True)
                    )
                ],
            )
        return dataset

    def get(self, identifier: str) -> Dataset:
        with self.store.connect() as connection:
            return Dataset.model_validate_json(
                dataset_row(connection, identifier)["metadata"]
            )

    def source_revision(self, identifier: str) -> str | None:
        with self.store.connect() as connection:
            return dataset_row(connection, identifier)["source_revision"]

    def list(self) -> DatasetList:
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT metadata FROM datasets WHERE deleted=0 ORDER BY rowid DESC LIMIT 256"
            )
            items = [Dataset.model_validate_json(row[0]) for row in rows]
        return DatasetList(items=items, total=len(items))

    def page(
        self, identifier: str, page: int = 1, page_size: int = 50, query: str = ""
    ) -> MoleculePage:
        if not 1 <= page <= 25000 or not 1 <= page_size <= 200 or len(query) > 200:
            raise WebError(422, "sar_page", "SAR page or search exceeds its limit.")
        # Escape LIKE controls; source IDs are literal values, not SQL patterns.
        pattern = (
            "%"
            + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        with self.store.connect() as connection:
            dataset_row(connection, identifier)
            where = "dataset_id=? AND (label LIKE ? ESCAPE '\\' OR json_extract(payload,'$.smiles') LIKE ? ESCAPE '\\')"
            total = connection.execute(
                "SELECT COUNT(*) FROM molecules WHERE " + where,
                (identifier, pattern, pattern),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT payload FROM molecules WHERE "
                + where
                + " ORDER BY ordinal LIMIT ? OFFSET ?",
                (identifier, pattern, pattern, page_size, (page - 1) * page_size),
            )
            items = [Molecule.model_validate_json(row[0]) for row in rows]
        return MoleculePage(items=items, total=total, page=page, page_size=page_size)

    def all(self, identifier: str) -> list[Molecule]:
        with self.store.connect() as connection:
            dataset_row(connection, identifier)
            items = [
                Molecule.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT payload FROM molecules WHERE dataset_id=? ORDER BY ordinal LIMIT 25001",
                    (identifier,),
                )
            ]
        if len(items) > 25000:
            raise WebError(
                413,
                "sar_dataset_limit",
                "SAR dataset exceeds its complete-input limit.",
            )
        return items

    def molecule(self, dataset_id: str, identifier: str) -> Molecule:
        with self.store.connect() as connection:
            dataset_row(connection, dataset_id)
            row = connection.execute(
                "SELECT payload FROM molecules WHERE dataset_id=? AND id=?",
                (dataset_id, identifier),
            ).fetchone()
        if row is None:
            raise WebError(
                404, "sar_molecule_missing", "Molecule is not in this SAR dataset."
            )
        return Molecule.model_validate_json(row[0])

    def region(self, identifier: str, dataset_id: str) -> Region:
        with self.store.connect() as connection:
            dataset_row(connection, dataset_id)
            row = connection.execute(
                "SELECT payload FROM regions WHERE id=? AND dataset_id=?",
                (identifier, dataset_id),
            ).fetchone()
        if row is None:
            raise WebError(
                404, "sar_region_missing", "Selected region is not in this SAR dataset."
            )
        return Region.model_validate_json(row[0])

    def save_region(self, region: Region) -> Region:
        with self.store.connect(write=True) as connection:
            dataset_row(connection, region.dataset_id)
            existing = connection.execute(
                "SELECT payload FROM regions WHERE id=?", (region.id,)
            ).fetchone()
            if existing:
                original = Region.model_validate_json(existing[0])
                if original.model_dump(exclude={"created_at"}) != region.model_dump(
                    exclude={"created_at"}
                ):
                    raise WebError(
                        409,
                        "sar_region_conflict",
                        "Region identity conflicts with its saved graph.",
                    )
                return original
            if (
                connection.execute(
                    "SELECT COUNT(*) FROM regions WHERE dataset_id=?",
                    (region.dataset_id,),
                ).fetchone()[0]
                >= 1000
            ):
                raise WebError(
                    413,
                    "sar_region_limit",
                    "SAR region retention limit has been reached.",
                )
            connection.execute(
                "INSERT INTO regions VALUES(?,?,?)",
                (region.id, region.dataset_id, region.model_dump_json()),
            )
        return region

    def remove(self, identifier: str) -> None:
        with self.store.connect(write=True) as connection:
            dataset_row(connection, identifier)
            if connection.execute(
                "SELECT 1 FROM jobs WHERE dataset_id=? AND (status IN ('queued','running') OR json_extract(payload,'$.error_code')='sar_process_unverified')",
                (identifier,),
            ).fetchone():
                raise WebError(
                    409,
                    "sar_active",
                    "Cancel the active SAR analysis before removing its dataset.",
                )
            connection.execute(
                "UPDATE datasets SET deleted=1 WHERE id=?", (identifier,)
            )
