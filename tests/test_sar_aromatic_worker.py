"""Rehashed partial-fragment tampering is not accepted as source evidence."""

import copy
import unittest

import test_sar_study_analysis as support

from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.assets import atomic_json, digest
from patent_sar_extractor.web.sar.models import Pair, SARJob
from patent_sar_extractor.web.sar.study_publication import verify_study


class AromaticWorkerTests(unittest.TestCase):
    setUp = support.StudyAnalysisTests.setUp
    packet = support.StudyAnalysisTests.packet
    write = support.StudyAnalysisTests.write
    run_packet = support.StudyAnalysisTests.run_packet

    def test_rehashed_aromatic_graph_and_reference_flag_tampering_are_rejected(self):
        packet = self.packet(
            rows=[
                support.molecule("1", "COc1ccccc1Cl", "10"),
                support.molecule("2", "COc1ccncc1Cl", "1"),
            ]
        )
        packet["regions"][0].update(atom_indices=[5], attachment_count=2)
        reply, report = self.run_packet(packet)
        safe = SafeFiles(self.root)
        pairs = [
            Pair.model_validate(item) for item in safe.json("chunk-0000.json")["pairs"]
        ]
        job = SARJob(
            id=packet["job_id"],
            dataset_id=packet["dataset"]["id"],
            region_id="",
            metric_id="activity",
            kind="study",
            status="running",
            processed=0,
            total=3,
            created_at=packet["dataset"]["created_at"],
            input_sha256=digest(packet),
        )
        verify_study(
            safe, job, {"engine_sha256": packet["engine_sha256"]}, reply, pairs
        )
        original = report.model_dump()
        for mode in ("different_graph", "wrong_reference"):
            altered = copy.deepcopy(original)
            fragments = altered["regions"][0]["fragments"]
            if mode == "different_graph":
                fragments[0]["graph_smiles"] = fragments[1]["graph_smiles"]
            else:
                fragments[0]["is_reference"] = False
            atomic_json(self.root, "report.json", altered)
            forged = {**reply, "report_sha256": digest(altered)}
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                verify_study(
                    safe, job, {"engine_sha256": packet["engine_sha256"]}, forged, pairs
                )
