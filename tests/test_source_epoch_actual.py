"""Opt-in read-only real-attempt transport proof; no recognizer/model is invoked.

The source is never opened through SQLite or an application workspace writer.
Only a fresh temporary destination receives copies. Private inputs are external.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.smiles_policy import _smiles_results_can_be_reused
from patent_sar_extractor.core.ocsr import stereo_gate
from patent_sar_extractor.web.acceptance import current
from patent_sar_extractor.web.attempts import ARTIFACTS, seed_checkpoints
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.processes import RunSpec, runtime_identity


def file_hashes(root: Path) -> dict[str, str]:
    paths = [path for path in root.rglob("*") if path.is_file()]
    if len(paths) > 25000 or any(path.is_symlink() for path in paths):
        raise ValueError("Unbounded or linked source proof input")
    output = {}
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        output[str(path.relative_to(root))] = digest.hexdigest()
    return output


def raw_rows(content: bytes) -> list[tuple]:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(content)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        return connection.execute(
            "SELECT * FROM smiles_observations ORDER BY image_hash,engine"
        ).fetchall()


@unittest.skipUnless(
    os.environ.get("PATENTSAR_SOURCE_EPOCH_PROOF_RUN"),
    "Private completed-attempt proof is explicit opt-in",
)
class ActualSourceEpochProofTests(unittest.TestCase):
    def test_full_upstream_and_raw_reuse_without_old_derived_proof(self):
        root = Path(os.environ["PATENTSAR_SOURCE_EPOCH_PROOF_RUN"])
        if (
            not root.is_absolute()
            or root.resolve() != root
            or any(parent.is_symlink() for parent in (root, *root.parents))
        ):
            raise ValueError("Proof requires an exact native, no-link source root")
        files = SafeFiles(root)
        summary = files.json("pipeline_summary.json")
        if summary.get("status") in {"running", "qa_pending"}:
            raise ValueError("Do not inspect an active attempt for transport proof")
        epoch = int(os.environ["PATENTSAR_SOURCE_EPOCH_PROOF_EPOCH"])
        before = file_hashes(root)
        classification = files.json(ARTIFACTS["classify"][0] + ".manifest.json")
        spec = RunSpec(
            job_id=root.name,
            project_id=root.parent.name,
            pdf_path=summary["input_pdf"],
            output_dir=str(root),
            patent_id=summary["patent_id"],
            sha256=classification["fingerprint"]["pdf_sha256"],
        )
        bindings = files.json(ARTIFACTS["bind"][0])
        activities = files.json(ARTIFACTS["activity"][0])
        smiles = files.json(ARTIFACTS["smiles"][0])
        observations = raw_rows(
            files.read("smiles/smiles_cache.sqlite", max_bytes=64 * 1024 * 1024)
        )
        successful = [
            row for row in observations if json.loads(row[2]).get("status") == "success"
        ]
        identity = runtime_identity()
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(core, "STEREO_EVIDENCE_VERSION", epoch),
            patch.object(stereo_gate, "STEREO_EVIDENCE_VERSION", epoch),
        ):
            target = Path(temporary) / "fresh-attempt"
            target.mkdir(mode=0o700)
            self.assertFalse(current(smiles, "smiles"))
            reusable, errors = _smiles_results_can_be_reused(
                smiles["records"], bindings
            )
            self.assertFalse(reusable)
            self.assertTrue(errors)
            self.assertEqual(runtime_identity(), identity)
            seed_checkpoints(spec, target)
            for stage in ("classify", "locate", "structures", "bind", "activity"):
                self.assertTrue((target / ARTIFACTS[stage][0]).is_file(), stage)
            for path in (
                ARTIFACTS["smiles"][0],
                "pipeline_summary.json",
                "final_qa_report.json",
                "STRICT_ACCEPTANCE_FAILED.json",
            ):
                self.assertFalse((target / path).exists(), path)
            copied = raw_rows((target / "smiles/smiles_cache.sqlite").read_bytes())
            self.assertEqual(copied, successful)
            print(
                "Actual epoch-only proof:",
                json.dumps(
                    {
                        "bound_records": len(bindings["final_bindings"]),
                        "activity_rows": len(activities["rows"]),
                        "raw_successful_observations": len(successful),
                        "source_review_records": sum(
                            record.get("OCSR_quality_flag") != "ok"
                            for record in smiles["records"]
                        ),
                        "upstream_checkpoints": 5,
                        "old_smiles_qa_copied": False,
                        "model_calls": 0,
                    },
                    sort_keys=True,
                ),
            )
        self.assertEqual(
            file_hashes(root), before, "Source attempt bytes must be unchanged"
        )


if __name__ == "__main__":
    unittest.main()
