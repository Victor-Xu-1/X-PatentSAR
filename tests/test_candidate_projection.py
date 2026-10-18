"""Native complete observations reach review only, not SAR/Lead/model inputs."""

import copy
import csv
import io
import json
import os
import unittest
from types import SimpleNamespace

from test_candidate_stage import CandidateStageControls

from patent_sar_extractor import contracts
from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.core.activity_coverage import coverage_packet
from patent_sar_extractor.web.artifacts import ArtifactView
from patent_sar_extractor.web.candidate_observations import read_source_observations
from patent_sar_extractor.web.exports import export_csv, export_json
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.lead_scoring import _refusal
from patent_sar_extractor.web.models import Acceptance, Compound
from patent_sar_extractor.web.prediction_identity import compound_prediction_eligible
from patent_sar_extractor.web.sar.source_scope import source_exclusion
from patent_sar_extractor.web.structure_corpus import unassociated_structures


class CandidateProjectionTests(CandidateStageControls, unittest.TestCase):
    def setUp(self):
        super().setUp()
        state = self.state()
        self.execute(state)
        self.payloads = {
            "structures": self.metadata,
            "bindings": self.bindings,
            "smiles": load_json(state.smiles_json, {}),
        }
        self.files = SafeFiles(self.output)

    def read(self, payloads=None, original=None):
        return read_source_observations(
            self.files,
            self.payloads if payloads is None else payloads,
            self.original_sha if original is None else original,
        )

    def view(self):
        # Declared earlier-stage transport controls, not an OCR/detector result.
        classification = self.output / "page_classification/page_classification.json"
        write_json_atomic(
            classification,
            {
                **contracts.artifact_identity(
                    contracts.PAGE_CLASSIFICATION_SCHEMA,
                    contracts.PAGE_CLASSIFICATION_SCHEMA_VERSION,
                ),
                "page_count": 3,
                "activity_pages": [],
            },
        )
        _write_step_manifest(
            str(classification), _step_fingerprint("classify", pdf_path=str(self.pdf))
        )
        write_json_atomic(
            self.output / "activity/activity_data.json",
            {
                **contracts.artifact_identity(
                    contracts.ACTIVITY_SCHEMA, contracts.ACTIVITY_SCHEMA_VERSION
                ),
                "rows": [],
                "active_cpds": [],
                "coverage": coverage_packet([], [], []),
            },
        )
        summary = load_json(self.output / "pipeline_summary.json", {})
        summary["steps"].update(
            {
                name: {"status": "ok"}
                for name in ("classify", "structures", "bind", "activity")
            }
        )
        write_json_atomic(self.output / "pipeline_summary.json", summary)
        return ArtifactView.read(self.output)

    def test_actual_snapshot_and_review_exports_keep_all_candidates_without_chemical_admission(
        self,
    ):
        view = self.view()
        snapshot, rows = view.snapshot("synthetic", pdf_sha256=self.original_sha)
        self.assertFalse(snapshot["is_historical"])
        self.assertNotEqual(snapshot["acceptance"]["state"], "accepted")
        self.assertEqual(len(rows), 2)
        molecules = [Compound.model_validate(row["dto"]) for row in rows]
        self.assertTrue(
            all(
                row.recognition.quality_flag == "unassigned_source_identity"
                for row in molecules
            )
        )
        project = SimpleNamespace(
            id="synthetic",
            patent_id="Synthetic",
            acceptance=Acceptance.model_validate(snapshot["acceptance"]),
        )
        exported = json.loads(b"".join(export_json(project, molecules)))
        self.assertTrue(exported["review_only"])
        self.assertEqual(len(exported["items"]), 2)
        self.assertTrue(
            all(
                row["smiles"] is None and row["activities"] == []
                for row in exported["items"]
            )
        )
        csv_rows = list(
            csv.DictReader(
                io.StringIO(
                    b"".join(export_csv(project, molecules)).decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(len(csv_rows), 2)
        self.assertTrue(
            all(not row["smiles"] and not row["identifier_label"] for row in csv_rows)
        )

    def test_snapshot_and_epoch_assessment_share_the_same_changed_source_refusal(self):
        view = self.view()
        source = self.metadata["structures"][1]["image_path"]
        with open(source, "ab") as stream:
            stream.write(b"changed controlled source bytes")
        accepted, historical, observations = view.assessment(
            pdf_sha256=self.original_sha
        )
        snapshot, rows = view.snapshot("synthetic", pdf_sha256=self.original_sha)
        self.assertFalse(historical)
        self.assertEqual(accepted.state, "failed")
        self.assertTrue(observations.errors)
        self.assertEqual(snapshot["acceptance"], accepted.model_dump())
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(row["dto"]["recognition"]["status"] == "unavailable" for row in rows)
        )

    def test_observed_candidates_are_not_misreported_as_unexecuted_or_named_products(
        self,
    ):
        before = {
            path: path.read_bytes() for path in self.output.rglob("*") if path.is_file()
        }
        observed = self.read()
        self.assertEqual(observed.errors, [])
        self.assertEqual(set(observed.records), {"S1", "S2"})
        rows, pages = unassociated_structures(
            "synthetic",
            self.metadata["structures"],
            set(),
            set(),
            self.files,
            verified_original=True,
            page_count=3,
            crop_revision="controlled",
            observations=observed.records,
        )
        self.assertEqual(pages, {1, 2})
        for row in rows:
            molecule = Compound.model_validate(row["dto"])
            self.assertEqual(molecule.recognition.status, "unavailable")
            self.assertEqual(
                molecule.recognition.quality_flag, "unassigned_source_identity"
            )
            self.assertEqual(molecule.recognition.model_fingerprint, "a" * 64)
            self.assertIsNone(molecule.smiles)
            self.assertIsNone(molecule.identifier_label)
            self.assertEqual(molecule.activities, [])
            self.assertFalse(compound_prediction_eligible(molecule))
            self.assertIsNotNone(_refusal(molecule))
            self.assertEqual(
                source_exclusion(molecule.display_id, molecule.id, molecule.flags),
                "unconfirmed_identifier",
            )
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_normal_access_time_changes_do_not_corrupt_read_only_source_replay(self):
        for row in self.metadata["structures"]:
            path = row["image_path"]
            os.utime(path, (0, os.stat(path).st_mtime))
        self.assertEqual(self.read().errors, [])

    def test_a_different_document_or_missing_candidate_result_is_not_a_current_view(
        self,
    ):
        self.assertTrue(self.read(original="f" * 64).errors)
        changed = copy.deepcopy(self.payloads)
        changed["smiles"]["candidate_records"].pop()
        rejected = self.read(changed)
        self.assertTrue(rejected.errors)
        self.assertEqual(rejected.records, {})

    def test_changed_or_linked_original_crops_remain_unaccepted(self):
        source = self.metadata["structures"][0]["image_path"]
        os.unlink(source)
        os.symlink(self.root / "source-1.png", source)
        rejected = self.read()
        self.assertTrue(rejected.errors)
        self.assertEqual(rejected.records, {})
