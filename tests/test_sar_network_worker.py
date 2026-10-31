"""Native single-site network, full publication and sealed-work recovery."""

import copy
import unittest
from unittest.mock import patch

import test_sar_study_analysis as support

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.assets import atomic_json
from patent_sar_extractor.web.sar.engine import engine_identity
from patent_sar_extractor.web.sar.models import Pair, SARJob
from patent_sar_extractor.web.sar.study_publication import verify_study
from patent_sar_extractor.workers.study_analysis import analyse_study


class NetworkWorkerTests(unittest.TestCase):
    setUp = support.StudyAnalysisTests.setUp
    packet = support.StudyAnalysisTests.packet
    write = support.StudyAnalysisTests.write
    run_packet = support.StudyAnalysisTests.run_packet

    def input(self, count=4):
        rows = [
            support.molecule(str(index + 1), smiles, str(index + 1))
            for index, smiles in enumerate(
                [
                    "COc1ccc(Cl)cc1",
                    "CCOc1ccc(Cl)cc1",
                    "COc1ccc(Br)cc1",
                    "CCCOc1ccc(Cl)cc1",
                ]
            )
        ]
        rows += [
            support.molecule(
                str(index + 1), "C" * (index + 1) + "Oc1ccc(Cl)cc1", str(index)
            )
            for index in range(4, count)
        ]
        packet = self.packet(rows=rows, regions=0)
        packet["request"]["discover_single_sites"] = True
        return packet

    def test_native_multiple_reference_network_and_parent_publication(self):
        packet = self.input()
        reply, report = self.run_packet(packet)
        self.assertEqual(
            {item.region.molecule_id for item in report.regions if item.matched},
            {"1", "2", "3", "4"},
        )
        self.assertTrue(all(item.origin == "single_site" for item in report.regions))
        self.assertEqual(
            report.discovery.candidate_comparisons, report.strict_pair_count
        )
        safe = SafeFiles(self.root)
        pairs = [
            Pair.model_validate(pair)
            for index in range(reply["chunks"])
            for pair in safe.json(f"chunk-{index:04d}.json")["pairs"]
        ]
        identities = {
            tuple(sorted((pair.reference_id, pair.molecule_id)))
            for pair in pairs
            if pair.match_status == "matched"
        }
        self.assertEqual(identities, {("1", "2"), ("1", "3"), ("1", "4"), ("2", "4")})
        job = SARJob(
            id=self.root.name,
            dataset_id=packet["dataset"]["id"],
            region_id="",
            metric_id="activity",
            kind="study",
            status="running",
            total=75004,
            created_at=packet["dataset"]["created_at"],
            input_sha256=reply["input_sha256"],
        )
        self.assertEqual(
            verify_study(
                safe, job, {"engine_sha256": packet["engine_sha256"]}, reply, pairs
            ),
            (reply["report_sha256"], 4),
        )
        self.assertEqual(analyse_study(self.root, reply["input_sha256"]), reply)

    def test_discovery_plan_tampering_never_creates_a_partial_success(self):
        packet = self.input()
        reply, _ = self.run_packet(packet)
        safe = SafeFiles(self.root)
        changed = copy.deepcopy(safe.json("network-plan.json"))
        changed["plans"][0]["candidate_ids"] = []
        atomic_json(self.root, "network-plan.json", changed)
        with self.assertRaises(SARInputError) as rejected:
            analyse_study(self.root, reply["input_sha256"])
        self.assertEqual(rejected.exception.code, "study_discovery_checkpoint_identity")

    def test_discovery_budget_failure_publishes_no_plan_or_partial_report(self):
        packet = self.input()
        input_sha = self.write(packet)
        with (
            patch("patent_sar_extractor.core.sar.discovery.MAX_PAIRS", 1),
            self.assertRaises(SARInputError) as rejected,
        ):
            analyse_study(self.root, input_sha)
        self.assertEqual(rejected.exception.code, "study_discovery_pair_limit")
        self.assertEqual({path.name for path in self.root.iterdir()}, {"input.json"})

    def test_prior_planning_epoch_cannot_resume_under_new_execution_semantics(self):
        packet = self.input()
        with patch("patent_sar_extractor.web.sar.engine.SAR_ENGINE_VERSION", 15):
            packet["engine_sha256"] = engine_identity()
        input_sha = self.write(packet)
        original = (self.root / "input.json").read_bytes()
        with self.assertRaises(SARInputError) as rejected:
            analyse_study(self.root, input_sha)
        self.assertEqual(rejected.exception.code, "study_input_identity")
        self.assertEqual((self.root / "input.json").read_bytes(), original)
        self.assertEqual({path.name for path in self.root.iterdir()}, {"input.json"})

    def test_interrupted_native_pair_batches_can_resume_without_replacing_the_plan(
        self,
    ):
        packet = self.input(16)
        input_sha = self.write(packet)
        with (
            patch(
                "patent_sar_extractor.workers.study_pairs.progress",
                side_effect=TimeoutError("controlled interruption"),
            ),
            self.assertRaises(TimeoutError),
        ):
            analyse_study(self.root, input_sha)
        safe = SafeFiles(self.root)
        original_plan = safe.read("network-plan.json", max_bytes=32 * 1024 * 1024)
        original_chunk = safe.read("chunk-0000.json", max_bytes=32 * 1024 * 1024)
        reply = analyse_study(self.root, input_sha)
        self.assertGreater(reply["chunks"], 1)
        self.assertEqual(
            safe.read("network-plan.json", max_bytes=32 * 1024 * 1024), original_plan
        )
        self.assertEqual(
            safe.read("chunk-0000.json", max_bytes=32 * 1024 * 1024), original_chunk
        )
