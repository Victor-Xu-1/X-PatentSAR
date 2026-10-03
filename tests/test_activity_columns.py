"""Stable activity-column catalogs on real private SQLite, with no inference."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from patent_sar_extractor.web import models
from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.corrections import Corrections
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.models import (
    Activity,
    Compound,
    Confidence,
    Results,
    Source,
)
from patent_sar_extractor.web.result_queries import ResultQueries
from patent_sar_extractor.web.storage import Store, encode, now


def measurement(**changes) -> Activity:
    return Activity.model_validate(
        {
            "name": "IC50",
            "value": "<10",
            "unit": "nM",
            "target": "JAK1",
            "assay": "cell",
            "page": None,
            **changes,
        }
    )


def compound(identifier: str, activities: list[Activity]) -> Compound:
    return Compound(
        id=identifier,
        display_id=identifier,
        activities=activities,
        source=Source(),
        confidence=Confidence(reason="Isolated source observation"),
        record_kind="activity_only" if activities else "structure_only",
    )


class ActivityColumnTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="activity-columns-", dir=tempfile.gettempdir()
        )
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name) / "state")
        self.project_id = "column-project"
        timestamp = now()
        with self.store.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO projects(id,title,patent_id,created_at,updated_at,snapshot) "
                "VALUES(?,?,?,?,?,?)",
                (
                    self.project_id,
                    "Isolated activity contexts",
                    "CONTRACT",
                    timestamp,
                    timestamp,
                    encode({"correction_projection_id": "original"}),
                ),
            )
        self.corrections = Corrections(self.store, self.store.project)
        self.query = ResultQueries(self.store, self.store.project)

    def insert(self, *rows: Compound) -> None:
        with self.store.connect(write=True) as connection:
            offset = connection.execute(
                "SELECT COUNT(*) FROM compounds WHERE project_id=?", (self.project_id,)
            ).fetchone()[0]
            connection.executemany(
                "INSERT INTO compounds(project_id,id,ordinal,payload,geometry_space) "
                "VALUES(?,?,?,?,?)",
                [
                    (
                        self.project_id,
                        row.id,
                        offset + index,
                        row.model_dump_json(),
                        "rendered",
                    )
                    for index, row in enumerate(rows)
                ],
            )

    @staticmethod
    def catalog(result: Results) -> list[dict]:
        return [column.model_dump() for column in result.activity_columns]

    def test_same_name_different_exact_contexts_produce_distinct_columns(self):
        values = [
            measurement(),
            measurement(unit="uM"),
            measurement(target="JAK2"),
            measurement(assay="biochemical"),
            measurement(unit=None),
            measurement(unit=""),
            measurement(name=" IC50 "),
        ]
        self.insert(compound("first", values))
        columns = self.catalog(self.query.results(self.project_id))
        self.assertEqual(len(columns), 7)
        self.assertEqual(len({column["id"] for column in columns}), 7)
        self.assertEqual(
            {
                (column["name"], column["unit"], column["target"], column["assay"])
                for column in columns
            },
            {(item.name, item.unit, item.target, item.assay) for item in values},
        )
        reference = next(
            column
            for column in columns
            if (column["name"], column["unit"], column["target"], column["assay"])
            == ("IC50", "nM", "JAK1", "cell")
        )
        self.assertEqual(
            reference["id"], hashlib.sha256(b'["IC50","nM","JAK1","cell"]').hexdigest()
        )

    def test_repeated_context_has_one_header_but_retains_every_value_and_source(self):
        values = [
            measurement(value="<10", page=1),
            measurement(value=15, page=2),
            measurement(value=None, page=None),
        ]
        self.insert(
            compound("first", values), compound("second", [measurement(value=0)])
        )
        result = self.query.results(self.project_id)
        self.assertEqual(len(result.activity_columns), 1)
        self.assertEqual(result.items[0].activities, values)
        self.assertEqual(result.items[1].activities[0].value, 0)

    def test_full_catalog_is_stable_across_pagination_and_all_filters(self):
        self.insert(
            compound("first", [measurement(name="A")]),
            compound("second", [measurement(name="Z", target="JAK2")]),
        )
        expected = self.catalog(self.query.results(self.project_id))
        for options in (
            {"page": 1, "page_size": 1},
            {"page": 2, "page_size": 1},
            {"page": 10, "page_size": 1},
            {"q": "first"},
            {"q": "no matching records"},
            {"target": "JAK2"},
            {"confidence": "high"},
            {"review": "approved"},
        ):
            with self.subTest(options=options):
                result = self.query.results(self.project_id, **options)
                self.assertEqual(self.catalog(result), expected)

    def test_no_activity_produces_empty_catalog_without_dropping_structures(self):
        self.assertEqual(self.query.results(self.project_id).activity_columns, [])
        self.insert(compound("structure", []))
        result = self.query.results(self.project_id)
        self.assertEqual(result.activity_columns, [])
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].id, "structure")

    def test_sort_and_ids_are_independent_of_row_and_measurement_order(self):
        self.insert(compound("first", [measurement(name="Z"), measurement(name="A")]))
        before = self.catalog(self.query.results(self.project_id))
        document = self.corrections.get(self.project_id, "first")
        self.corrections.put(
            self.project_id,
            "first",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=document.values.model_copy(
                    update={"activities": list(reversed(document.values.activities))}
                ),
            ),
        )
        self.assertEqual(self.catalog(self.query.results(self.project_id)), before)
        self.assertEqual([column["name"] for column in before], ["A", "Z"])

    def test_current_edit_changes_whole_catalog_even_when_edited_row_is_filtered_out(
        self,
    ):
        self.insert(
            compound("first", [measurement(name="A")]),
            compound("second", [measurement(name="Z")]),
        )
        raw = self.store.compound(self.project_id, "second")["payload"]
        document = self.corrections.get(self.project_id, "second")
        edited = measurement(name="B", target="Edited target", assay="Edited assay")
        self.corrections.put(
            self.project_id,
            "second",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=document.values.model_copy(update={"activities": [edited]}),
            ),
        )
        result = self.query.results(self.project_id, q="first")
        self.assertEqual([item.id for item in result.items], ["first"])
        self.assertEqual(
            [column.name for column in result.activity_columns], ["A", "B"]
        )
        self.assertEqual(result.activity_columns[1].target, "Edited target")
        self.assertEqual(self.store.compound(self.project_id, "second")["payload"], raw)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM correction_audit").fetchone()[
                    0
                ],
                1,
            )

    def test_stale_edits_do_not_promote_old_column_contexts(self):
        self.insert(compound("first", [measurement(name="Original")]))
        document = self.corrections.get(self.project_id, "first")
        self.corrections.put(
            self.project_id,
            "first",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=document.values.model_copy(
                    update={"activities": [measurement(name="Edited")]}
                ),
            ),
        )
        with self.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (encode({"correction_projection_id": "new-source"}), self.project_id),
            )
        result = self.query.results(self.project_id)
        self.assertEqual(
            [column.name for column in result.activity_columns], ["Original"]
        )
        correction = result.items[0].correction
        assert correction is not None
        self.assertTrue(correction.stale)

    def test_catalog_limit_fails_explicitly_even_if_filter_hides_overflow(self):
        values = [measurement(assay=f"Assay {index:04d}") for index in range(1000)]
        self.insert(compound("first", values))
        self.assertEqual(
            len(self.query.results(self.project_id).activity_columns), 1000
        )
        self.insert(compound("second", [measurement(assay="Assay 1000")]))
        with self.assertRaises(WebError) as caught:
            self.query.results(self.project_id, q="no matching rows")
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.code, "activity_column_limit")

    def test_catalog_uses_the_existing_bounded_read_without_row_sql_or_pdf_loads(self):
        self.insert(compound("first", [measurement()]))
        connect = self.store.connect
        statements: list[str] = []

        @contextmanager
        def traced(*args, **kwargs):
            with connect(*args, **kwargs) as connection:
                connection.set_trace_callback(statements.append)
                yield connection

        counts = []
        for size in (1, 100):
            if size > 1:
                self.insert(
                    *(
                        compound(f"row-{index}", [measurement()])
                        for index in range(1, size)
                    )
                )
            with (
                patch.object(self.store, "connect", traced),
                patch("patent_sar_extractor.web.result_queries.open_pdf") as open_pdf,
            ):
                statements.clear()
                result = self.query.results(self.project_id, page_size=100)
                self.assertEqual(result.total, size)
                self.assertEqual(len(result.activity_columns), 1)
                open_pdf.assert_not_called()
                counts.append(
                    sum(sql.lstrip().upper().startswith("SELECT") for sql in statements)
                )
        self.assertEqual(counts, [4, 4])

    def test_utf8_context_and_missing_values_are_preserved_without_normalization(self):
        name = '活性 "等级" / 实验\\观察'
        values = [
            measurement(name=name, unit=None, target=None, assay="实验甲"),
            measurement(name=name, unit=None, target="", assay="实验甲"),
        ]
        self.insert(compound("first", values))
        result = self.query.results(self.project_id)
        self.assertEqual(len(result.activity_columns), 2)
        expected = '["活性 \\"等级\\" / 实验\\\\观察",null,null,"实验甲"]'.encode()
        self.assertEqual(
            result.activity_columns[0].id, hashlib.sha256(expected).hexdigest()
        )
        self.assertIsNone(result.activity_columns[0].target)
        self.assertEqual(result.activity_columns[1].target, "")

    def test_additive_dto_defaults_and_bounded_hash_shape(self):
        result = Results(
            items=[], total=0, page=1, page_size=10, metrics=[], targets=[]
        )
        self.assertEqual(result.activity_columns, [])
        column_type = models.ActivityColumn
        for invalid in ("", "A" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n", 1):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                column_type.model_validate(
                    {
                        "id": invalid,
                        "name": "IC50",
                        "unit": None,
                        "target": None,
                        "assay": None,
                    }
                )
        valid = column_type(
            id="a" * 64, name="IC50", unit=None, target=None, assay=None
        )
        with self.assertRaises(ValidationError):
            Results(
                items=[],
                total=0,
                page=1,
                page_size=10,
                metrics=[],
                targets=[],
                activity_columns=[valid] * 1001,
            )

    def test_invalid_utf8_is_rejected_instead_of_repaired_into_another_context(self):
        from patent_sar_extractor.web.activity_columns import activity_column_id

        with self.assertRaises(WebError) as caught:
            activity_column_id(("\ud800", None, None, None))
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.code, "invalid_activity_column")


if __name__ == "__main__":
    unittest.main()
