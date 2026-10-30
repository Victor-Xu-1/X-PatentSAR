"""Large generated activity evidence uses the existing bounded artifact codec."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core.activity_artifacts import (
    save_results,
    write_activity_payload,
)
from patent_sar_extractor.core.activity_models import ActivityRow
from patent_sar_extractor.web.attempts import CheckpointCopy, VerifiedCheckpoint
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import MAX_ARTIFACT_BYTES, SafeFiles
from patent_sar_extractor.web.processes import RunSpec


class ActivityTransportBudgetTests(unittest.TestCase):
    def test_original_source_evidence_roundtrips_without_reinflation_or_row_truncation(
        self,
    ):
        evidence = {
            "method": "controlled-original-observation",
            "text": "CONTROLLED ORIGINAL SOURCE LINE " * 1200,
        }
        original = copy.deepcopy(evidence)
        rows = [
            ActivityRow(
                cpd=f"I-{number:04d}",
                page_no=1,
                needs_review=True,
                activity_values={"IC50 (nM)": str(number + 1)},
            )
            for number in range(1000)
        ]
        unresolved = [
            {
                "row_index": number,
                "reason": "controlled-unresolved",
                "original": evidence,
            }
            for number in range(1000)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_results(
                rows,
                root,
                {"patent_id": "CONTROLLED-TRANSPORT"},
                coverage={},
                unresolved_rows=unresolved,
            )
            path = root / "activity_data.json"
            self.assertLessEqual(path.stat().st_size, MAX_ARTIFACT_BYTES)
            restored = SafeFiles(root).json(path.name, optional=False)
            self.assertEqual(len(restored["rows"]), len(rows))
            self.assertEqual(len(restored["unresolved_rows"]), len(unresolved))
            for index, row in enumerate(restored["rows"]):
                self.assertEqual(row["cpd"], rows[index].cpd)
                self.assertTrue(row["needs_review"])
                self.assertEqual(row["activity_values"], rows[index].activity_values)
            self.assertEqual(
                [row["original"] for row in restored["unresolved_rows"]],
                [original] * 1000,
            )
            # Transport-only construction: does not approve a scientific checkpoint.
            transport = CheckpointCopy(root, root / "new-attempt")
            transport.checkpoint(
                VerifiedCheckpoint(
                    "activity",
                    path.name,
                    restored,
                    {"fingerprint": {"params": {}, "dependency_sha256": {}}},
                )
            )
            resumed = SafeFiles(transport.target).json(path.name, optional=False)
            self.assertEqual(resumed, restored)
            self.assertLessEqual(
                (transport.target / path.name).stat().st_size, MAX_ARTIFACT_BYTES
            )
        self.assertEqual(evidence, original)

    def test_oversized_legacy_activity_is_preserved_without_parsing_or_copying(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prior"
            path = source / "activity/activity_data.json"
            path.parent.mkdir(parents=True)
            with path.open("wb") as output:
                output.seek(MAX_ARTIFACT_BYTES)
                output.write(b" ")
            before = path.stat()
            transport = CheckpointCopy(source, root / "next")
            spec = RunSpec(
                "a" * 32, "b" * 32, "unused.pdf", str(source), "CONTROL", "c" * 64
            )
            with patch.object(
                transport.files,
                "json",
                side_effect=AssertionError("Do not parse oversized legacy"),
            ):
                self.assertIsNone(transport.verify("activity", spec))
            after = path.stat()
            self.assertEqual(
                (before.st_ino, before.st_size, before.st_mtime_ns),
                (after.st_ino, after.st_size, after.st_mtime_ns),
            )
            self.assertEqual(list(transport.target.iterdir()), [])

    def test_actual_sar_condition_consumer_uses_shared_reader_and_exact_file_digest(
        self,
    ):
        from patent_sar_extractor.web.artifacts import _activities
        from patent_sar_extractor.web.sar.observation_contexts import (
            ObservationContexts,
        )
        from tests.test_activity_source_scopes import source_row

        rows = [source_row(1), source_row(2, cell_line="A549")]
        original = copy.deepcopy(rows)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "activity"
            directory.mkdir()
            path = directory / "activity_data.json"
            repeated = {"text": "CONTROLLED ORIGINAL " * 500}
            write_activity_payload(
                path, {"rows": rows, "unresolved_rows": [repeated, repeated]}
            )
            data = path.read_bytes()
            self.assertIn(b'"_shared_json"', data)
            project = {
                "run_root": str(root),
                "sha256": "a" * 64,
                "expected_sha256": "a" * 64,
                "page_count": 5,
            }
            contexts = ObservationContexts(project)
            self.assertEqual(contexts.source_sha256, hashlib.sha256(data).hexdigest())
            for row, expected in zip(rows, ("HEK293", "A549"), strict=True):
                activity = _activities(row, page_count=5, document_sha256="a" * 64)[0]
                selected = contexts.contexts("1", activity)
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]["cell_line"], expected)
            damaged = json.loads(data)
            key = next(iter(damaged["_shared_json"]["objects"]))
            damaged["_shared_json"]["objects"][key] = {"changed": True}
            path.write_text(json.dumps(damaged))  # This generated fixture only.
            for read in (
                lambda: SafeFiles(root).json("activity/activity_data.json"),
                lambda: ObservationContexts(project),
            ):
                with self.assertRaises(WebError) as captured:
                    read()
                self.assertEqual(captured.exception.code, "invalid_artifact")
        self.assertEqual(rows, original)

    def test_unique_over_budget_output_stays_rejected_without_replacing_old_json(self):
        from patent_sar_extractor import artifact_io

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity_data.json"
            before = b'{"controlled_original":true}'
            path.write_bytes(before)
            with (
                patch.object(artifact_io, "MAX_ARTIFACT_BYTES", 1024),
                self.assertRaises(ValueError),
            ):
                write_activity_payload(path, {"rows": [], "unresolved": "x" * 2000})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])
        self.assertEqual(MAX_ARTIFACT_BYTES, 32 * 1024 * 1024)

    def test_application_annotation_reuses_the_same_bounded_writer(self):
        from patent_sar_extractor.application.activity_policy import (
            _annotate_activity_payload,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "activity_data.json"
            evidence = {"text": "CONTROLLED ORIGINAL " * 500}
            rows = [{"cpd": "I-001", "activity_values": {"IC50 (nM)": "3"}}]
            write_activity_payload(
                path, {"rows": rows, "unresolved_rows": [evidence, evidence]}
            )
            self.assertEqual(_annotate_activity_payload(str(path)), ["Compound I-001"])
            self.assertIn(b'"_shared_json"', path.read_bytes())
            result = SafeFiles(root).json(path.name)
            self.assertEqual(result["rows"], rows)
            self.assertEqual(result["unresolved_rows"], [evidence, evidence])
