"""Controlled transport stress, not source recognition or chemical acceptance."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.contracts import (
    COMPOUND_CATALOG_SCHEMA,
    COMPOUND_CATALOG_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.web.attempts import CheckpointCopy, VerifiedCheckpoint
from patent_sar_extractor.web.files import MAX_ARTIFACT_BYTES, SafeFiles
from patent_sar_extractor.web.processes import RunSpec


class BindingTransportBudgetTests(unittest.TestCase):
    def test_oversized_legacy_binding_checkpoint_is_left_for_fresh_producer_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "old-attempt"
            path = source / "structure_bindings/bindings.json"
            path.parent.mkdir(parents=True)
            with path.open("wb") as stream:
                stream.seek(MAX_ARTIFACT_BYTES)
                stream.write(b" ")
            original = path.stat()
            transport = CheckpointCopy(source, Path(temporary) / "new-attempt")
            spec = RunSpec(
                "a" * 32, "b" * 32, "unused.pdf", str(source), "CONTROL", "c" * 64
            )
            with patch.object(
                transport.files,
                "json",
                side_effect=AssertionError("Oversized legacy must not be parsed"),
            ):
                self.assertIsNone(transport.verify("bind", spec))
            current = path.stat()
            self.assertEqual(
                (current.st_ino, current.st_size, current.st_mtime_ns),
                (original.st_ino, original.st_size, original.st_mtime_ns),
            )
            self.assertEqual(list(transport.target.iterdir()), [])

    def test_shared_original_evidence_is_lossless_and_readable_under_the_same_budget(
        self,
    ):
        # The catalogue adapter isolates serialization, not scientific proof.
        # One shared observation must not be copied per row and again per view.
        proof = {
            "method": "controlled_original_observation",
            "text": "CONTROLLED ORIGINAL SOURCE LINE " * 1200,
            "bbox": [10, 20, 30, 40],
        }
        original = copy.deepcopy(proof)
        rows = [
            {
                "cpd": f"Compound {number}",
                "compound_id": str(number),
                "structure_id": f"synthetic-source-{number}",
                "page_no": number,
                "accuracy_status": "confirmed",
                "evidence_tier": "strong",
                "fail_closed": False,
                "original_label_evidence": proof,
                "additional_sources": [],
            }
            for number in range(1, 1001)
        ]
        catalog = {
            "schema": schema_ref(
                COMPOUND_CATALOG_SCHEMA, COMPOUND_CATALOG_SCHEMA_VERSION
            ),
            "authority": "printed_identifier_and_original_spatial_evidence",
            "entries": rows,
            "numbered_compounds": len(rows),
            "source_observations": len(rows),
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch(
                "patent_sar_extractor.core.binding_artifacts.compound_catalog",
                return_value=catalog,
            ):
                write_binding_result(
                    directory,
                    patent_id="CONTROLLED-TRANSPORT",
                    bindings=rows,
                    detected_style="original_cell_caption_heading",
                    include_intermediates=False,
                    total_structures=len(rows),
                    total_compound_blocks=len(rows),
                    table_pages=[],
                    table_covered_count=len(rows),
                    no_binding=[],
                    unbound_pages=[],
                    original_pdf_sha256="a" * 64,
                )
            path = directory / "bindings.json"
            self.assertLessEqual(path.stat().st_size, MAX_ARTIFACT_BYTES)
            restored = SafeFiles(directory).json("bindings.json", optional=False)
            # Transport-only adapter, not scientific checkpoint approval. The
            # real copy must not re-inflate an already bounded binding output.
            transport = CheckpointCopy(directory, directory / "next-attempt")
            transport.checkpoint(
                VerifiedCheckpoint(
                    "bind",
                    "bindings.json",
                    restored,
                    {"fingerprint": {"params": {}, "dependency_sha256": {}}},
                )
            )
            resumed = SafeFiles(transport.target).json("bindings.json", optional=False)
            self.assertEqual(resumed, restored)
        self.assertEqual(len(restored["compound_catalog"]["entries"]), len(rows))
        self.assertNotIn("final_bindings", restored)
        for row in restored["compound_catalog"]["entries"]:
            self.assertEqual(row["original_label_evidence"], original)
        self.assertEqual(proof, original)


if __name__ == "__main__":
    unittest.main()
