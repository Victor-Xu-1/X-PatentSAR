"""The real worker-plan entry reopens generated role originals, without models."""

import copy
import hashlib
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from patent_sar_extractor.core.ocsr.candidate_inputs import load_source_observation_plan
from patent_sar_extractor.core.ocsr.recognition_inputs import RecognitionPlan
from patent_sar_extractor.core.role_text_sources import role_text_cells
from patent_sar_extractor.core.structure_inventory import inventory_packet
from tests import test_candidate_observations as candidates
from tests import test_role_original_replay as roles


class RoleOriginalConsumerTests(unittest.TestCase):
    def setUp(self):
        fixture = candidates.CandidateObservationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source = roles.PrimaryRoleReplayTests()
        self.addCleanup(source.doCleanups)
        page, payload = source.source("native")
        original = fixture.root / "role-original.pdf"
        with fitz.open(fixture.pdf) as document:
            document.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
            document.save(original)
        fixture.pdf = original
        fixture.original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
        fixture.owner["source_pdf_sha256"] = fixture.original_sha
        fixture.manifest["fingerprint"]["pdf_sha256"] = fixture.original_sha
        fixture.manifest["fingerprint"]["params"]["structure_pages"] = [0, 1, 2, 3]
        fixture.metadata["source_inventory"] = inventory_packet(
            4,
            [
                {
                    "page_no": number,
                    "status": "detected",
                    "scope": "full_page",
                    "candidates": count,
                }
                for number, count in ((1, 1), (2, 1), (3, 0), (4, 0))
            ],
        )
        payload["coverage"]["regions"][0]["page_no"] = 4
        metadata = fixture.root / "metadata.json"
        write_json_atomic(metadata, fixture.metadata)
        write_json_atomic(str(metadata) + ".manifest.json", fixture.manifest)
        self.fixture, self.payload, self.metadata = fixture, payload, metadata

    def load(self, payload):
        sources = RecognitionPlan(
            [self.fixture.owner], [], [], role_text=tuple(role_text_cells(payload))
        )
        return load_source_observation_plan(
            sources,
            structures_json=self.metadata,
            pdf_path=self.fixture.pdf,
            binding_dir=self.fixture.root,
            binding_pdf_sha256=self.fixture.original_sha,
        )

    def test_actual_worker_plan_replays_the_role_page_without_recognizing_it(self):
        with patch(
            "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
            side_effect=AssertionError("Original-only plan read cannot invoke OCR"),
        ):
            plan = self.load(self.payload)
        self.assertEqual(len(plan.proven.role_text), 6)
        self.assertEqual(len(plan.proven.work_items), 1)
        self.assertEqual(len(plan.work_items), 2)
        self.assertTrue(all(page_no == 4 for page_no, _ in plan.proven.role_text))

    def test_pure_qualified_but_rewritten_native_role_is_rejected_by_actual_worker(
        self,
    ):
        changed = copy.deepcopy(self.payload)
        record = changed["coverage"]["regions"][0]
        scope = record["role_scope"]
        replacement = scope["observations"][0]["matrix"][1][2].replace("7.2", "8.4")
        scope["observations"][0]["matrix"][1][2] = replacement
        scope["observations"][0]["cells"][5]["text"] = replacement
        scope["native_hints"][1][2] = replacement
        self.assertTrue(
            valid_role_scope(record),
            "This remains pure qualified text; original replay must independently refuse it",
        )
        with self.assertRaisesRegex(
            ValueError, "Original binding/source replay failed"
        ):
            self.load(changed)
