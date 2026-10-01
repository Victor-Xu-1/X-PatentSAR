"""Real SQLite snapshot safety and exact-observation transport regressions."""

from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing

from patent_sar_extractor.contracts import OCSR_OBSERVATION_VERSION
from patent_sar_extractor.core.ocsr.cache_snapshot import snapshot_observations
from patent_sar_extractor.core.ocsr.smiles_cache import OBSERVATIONS_SQL


class RawSnapshotTests(unittest.TestCase):
    identity = "f" * 64

    def observation(self, **changes):
        payload = {
            "status": "success",
            "model_fingerprint": self.identity,
            "raw_smiles": "C[C@H](O)Cl",
            "token_confidence": 0.87,
        }
        payload.update(changes)
        return (
            "a" * 64,
            f"decimer:raw-v{OCSR_OBSERVATION_VERSION}:{self.identity}",
            json.dumps(payload),
            "2026-10-01T00:00:00+00:00",
        )

    def database(self, rows, *, view=False, extra_schema=False):
        with closing(sqlite3.connect(":memory:")) as connection:
            if view:
                connection.execute(
                    "CREATE VIEW smiles_observations AS SELECT 'x' AS image_hash"
                )
            else:
                connection.execute(OBSERVATIONS_SQL)
                connection.executemany(
                    "INSERT INTO smiles_observations VALUES (?,?,?,?)", rows
                )
            if extra_schema:
                connection.execute("CREATE TABLE legacy_repaired(payload TEXT)")
                connection.execute(
                    "CREATE TRIGGER foreign_write AFTER INSERT ON smiles_observations "
                    "BEGIN INSERT INTO legacy_repaired VALUES ('foreign'); END"
                )
            connection.commit()
            return connection.serialize()

    def snapshot(self, content, *, max_bytes=32768, max_records=10):
        return snapshot_observations(
            content, max_bytes=max_bytes, max_records=max_records
        )

    def test_payload_timestamp_and_stereo_are_exact_without_foreign_schema(self):
        row = self.observation()
        content = self.database([row], extra_schema=True)
        snapshot = self.snapshot(content)
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(snapshot)
            self.assertEqual(
                connection.execute("SELECT * FROM smiles_observations").fetchall(),
                [row],
            )
            schema = connection.execute(
                "SELECT type,name FROM sqlite_schema WHERE type IN ('table','trigger')"
            ).fetchall()
            self.assertEqual(schema, [("table", "smiles_observations")])
        self.assertEqual(content, self.database([row], extra_schema=True))

    def test_timeouts_and_legacy_repaired_epochs_are_not_promoted(self):
        row = self.observation()
        timeout = self.observation(
            status="timeout", model_fingerprint=None, raw_smiles=None
        )
        timeout = ("b" * 64, *timeout[1:])
        legacy = ("c" * 64, "decimer", '{"raw_smiles":"CO"}', row[3])
        snapshot = self.snapshot(self.database([row, timeout, legacy]))
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(snapshot)
            self.assertEqual(
                connection.execute("SELECT * FROM smiles_observations").fetchall(),
                [row],
            )

    def test_foreign_view_corruption_size_and_record_limits_are_refused(self):
        cases = (
            lambda: self.snapshot(b"not a sqlite database"),
            lambda: self.snapshot(self.database([], view=True)),
            lambda: self.snapshot(self.database([self.observation()]), max_bytes=16),
            lambda: self.snapshot(self.database([self.observation()]), max_records=0),
            lambda: self.snapshot(
                self.database(
                    [self.observation(), ("b" * 64, *self.observation()[1:])]
                ),
                max_records=1,
            ),
        )
        for run in cases:
            with self.subTest(run=run), self.assertRaises((ValueError, sqlite3.Error)):
                run()

    def test_invalid_model_identity_json_and_raw_type_are_refused(self):
        row = self.observation()
        cases = (
            self.observation(model_fingerprint="e" * 64),
            self.observation(raw_smiles=123),
            ("not-a-hash", *row[1:]),
            (row[0], row[1], '{"confidence":NaN}', row[3]),
            (row[0], row[1], "[]", row[3]),
            (row[0], row[1], '"' + "x" * 65536 + '"', row[3]),
        )
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.snapshot(self.database([invalid]), max_bytes=131072)


if __name__ == "__main__":
    unittest.main()
