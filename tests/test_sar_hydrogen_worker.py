"""Hydrogen checkpoint recovery and strict parent proof rejection."""

import unittest
from unittest.mock import patch

import test_sar_study_analysis as support

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.models import Pair, SARJob
from patent_sar_extractor.web.sar.study_publication import verify_study
from patent_sar_extractor.workers.study_analysis import analyse_study


class HydrogenWorkerTests(unittest.TestCase):
    setUp = support.StudyAnalysisTests.setUp
    packet = support.StudyAnalysisTests.packet
    write = support.StudyAnalysisTests.write
    run_packet = support.StudyAnalysisTests.run_packet

    def input(self):
        packet = self.packet(
            rows=[
                support.molecule(str(index + 1), smiles)
                for index, smiles in enumerate(
                    [
                        "COc1ccccc1Cl",
                        "COc1c(F)cccc1Cl",
                        "COc1c(C)cccc1Cl",
                        "COc1c(Br)cccc1Cl",
                        "COc1ccc(F)cc1Cl",
                    ]
                )
            ],
            regions=0,
        )
        packet["request"]["discover_single_sites"] = True
        return packet

    def test_rehashed_valid_range_hydrogen_anchor_cannot_fake_a_parent_proof(self):
        packet = self.input()
        reply, _ = self.run_packet(packet)
        safe = SafeFiles(self.root)
        pairs = [
            Pair.model_validate(pair)
            for index in range(reply["chunks"])
            for pair in safe.json(f"chunk-{index:04d}.json")["pairs"]
        ]
        target = next(
            pair for pair in pairs if pair.candidate_hydrogen_anchor is not None
        )
        payload = target.model_dump()
        payload["candidate_hydrogen_anchor"] = 5
        payload["attachment_mapping"][0][1] = 5
        forged = Pair.model_validate(payload)
        changed = [forged if pair is target else pair for pair in pairs]
        job = SARJob(
            id=self.root.name,
            dataset_id=packet["dataset"]["id"],
            region_id="",
            metric_id="activity",
            kind="study",
            status="running",
            total=75005,
            created_at=packet["dataset"]["created_at"],
            input_sha256=reply["input_sha256"],
        )
        self.assertEqual(
            verify_study(
                safe, job, {"engine_sha256": packet["engine_sha256"]}, reply, pairs
            ),
            (reply["report_sha256"], 5),
        )
        with self.assertRaises(WebError) as rejected:
            verify_study(
                safe, job, {"engine_sha256": packet["engine_sha256"]}, reply, changed
            )
        self.assertEqual(rejected.exception.code, "sar_result_invalid")

    def test_interruption_retains_hydrogen_plan_and_sealed_pair_bytes(self):
        packet = self.input()
        sha = self.write(packet)
        with (
            patch(
                "patent_sar_extractor.workers.study_pairs.progress",
                side_effect=TimeoutError("controlled H interruption"),
            ),
            self.assertRaises(TimeoutError),
        ):
            analyse_study(self.root, sha)
        safe = SafeFiles(self.root)
        plan = safe.read("network-plan.json", max_bytes=32 * 1024 * 1024)
        chunk = safe.read("chunk-0000.json", max_bytes=32 * 1024 * 1024)
        self.assertTrue(
            any(
                item["region"].get("hydrogen_anchor") is not None
                for item in safe.json("network-plan.json")["plans"]
            )
        )
        reply = analyse_study(self.root, sha)
        self.assertEqual(
            safe.read("network-plan.json", max_bytes=32 * 1024 * 1024), plan
        )
        self.assertEqual(
            safe.read("chunk-0000.json", max_bytes=32 * 1024 * 1024), chunk
        )
        self.assertEqual(analyse_study(self.root, sha), reply)


if __name__ == "__main__":
    unittest.main()
