"""Current tenth-dose views over preserved historical synthetic reports."""

import copy
import json
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

import test_sar_api as support
import test_sar_study_analysis as study_support
from test_web_support import WebFixture

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.admission import existing
from patent_sar_extractor.web.sar.assets import digest
from patent_sar_extractor.web.sar.models import (
    AnalysisRequest,
    Dataset,
    Molecule,
    SARJob,
)
from patent_sar_extractor.web.sar.source_scope import source_exclusion
from patent_sar_extractor.web.sar.study_current import _derive
from patent_sar_extractor.web.sar.study_models import StudyReport
from patent_sar_extractor.web.sar.study_view import current_report
from patent_sar_extractor.web.sar.study_view_groups import GroupBins
from patent_sar_extractor.web.storage import encode

molecule = study_support.molecule
policy = study_support.policy


class CurrentStrengthTests(unittest.TestCase):
    setUp = study_support.StudyAnalysisTests.setUp
    packet = study_support.StudyAnalysisTests.packet
    write = study_support.StudyAnalysisTests.write
    run_packet = study_support.StudyAnalysisTests.run_packet

    def test_group_bin_preparation_is_bounded_and_returns_independent_count_objects(
        self,
    ):
        domain = Mock()
        domain.for_members.side_effect = lambda members: {
            "bins": [
                {
                    "label": "missing",
                    "kind": "missing",
                    "strong": False,
                    "molecules": len(members),
                    "observations": 0,
                }
            ]
        }
        cache = GroupBins(domain)
        first = cache.for_members(["B", "A"])
        first[0].molecules = 999
        second = cache.for_members(["A", "B"])
        self.assertEqual(second[0].molecules, 2)
        self.assertEqual(domain.for_members.call_count, 1)
        for index in range(300):
            cache.for_members([str(index)])
        self.assertLessEqual(len(cache._items), 256)
        self.assertLessEqual(sum(len(key) for key in cache._items), 4096)
        cache.for_members([str(index) for index in range(4097)])
        self.assertLessEqual(sum(len(key) for key in cache._items), 4096)

    def test_receipt_validated_large_view_reuses_one_model_without_changing_projection(
        self,
    ):
        packet, captured = self.historical(["0.1"] * 9 + ["1", "10", "100", ""])
        original = copy.deepcopy(captured.model_dump())
        expected, exclusions = current_report(packet, captured, [])
        with patch.object(
            StudyReport,
            "model_validate_json",
            side_effect=AssertionError("duplicate parse"),
        ):
            current, actual_exclusions = _derive(
                encode(packet).encode(),
                encode(original).encode(),
                b"[]",
                captured=captured,
            )
        self.assertEqual(current.model_dump(), expected.model_dump())
        self.assertEqual(actual_exclusions, exclusions)
        self.assertEqual(captured.model_dump(), original)

    def historical(self, values):
        rows = [
            molecule(f"S{index + 1}", "COc1ccc(Cl)cc1", value)
            for index, value in enumerate(values)
        ]
        packet = self.packet(
            rows=rows, regions=0, policies=[policy(strong_threshold=1.0)]
        )
        _, report = self.run_packet(packet)
        return packet, report

    def test_historical_fixed_threshold_becomes_tenth_decade_in_current_view_only(self):
        packet, captured = self.historical(
            ["0.1"] * 9 + ["1", "9", "10", "99", "100", ""]
        )
        original = copy.deepcopy(captured.model_dump())
        current, excluded = current_report(packet, captured, [])
        scale = current.policies[0].strength_scale
        self.assertEqual(
            (scale.anchor_rank, scale.strong_boundary, scale.medium_boundary),
            (10, 10, 100),
        )
        bins = {item.label: item.molecules for item in current.distributions[0].bins}
        self.assertEqual(
            (bins["strong"], bins["medium"], bins["weak"], bins["missing"]),
            (11, 2, 1, 1),
        )
        context = current.policies[0].context_id
        self.assertEqual(current.rows[9].activity_bands[context], "strong")
        self.assertEqual(captured.model_dump(), original)
        self.assertEqual(excluded, {})

    def test_numberless_and_explicit_intermediate_records_do_not_set_the_anchor(self):
        baseline, report = self.historical(["0.1"] * 9 + ["10", "100", "1000", ""])
        for label in (
            "Intermediate 2",
            " Intermediates 2 ",
            "interm. 2",
            "中间体2",
            "中間体2",
            "中間體2",
        ):
            with self.subTest(label=label):
                packet, captured = copy.deepcopy(baseline), report.model_copy(deep=True)
                # Archive observations remain intact; the current population is scoped.
                packet["molecules"][0]["source_compound_id"] = (
                    " SOURCE-STRUCTURE:unconfirmed "
                )
                packet["molecules"][1]["label"] = label
                captured.rows[1].label = label
                original = copy.deepcopy(packet)
                current, excluded = current_report(packet, captured, [])
                self.assertEqual(current.molecule_count, 11)
                self.assertEqual(
                    current.policies[0].strength_scale.strong_boundary, 10000
                )
                self.assertEqual(
                    excluded, {"unconfirmed_identifier": 1, "intermediate": 1}
                )
                self.assertFalse(any(row.label == label for row in current.rows))
                self.assertEqual(packet, original)

    def test_fewer_than_ten_and_uncertain_tenth_never_fall_back_to_fifth(self):
        packet, captured = self.historical(["1"] * 5 + ["10"] * 4)
        current, _ = current_report(packet, captured, [])
        self.assertEqual(current.policies[0].strength_scale.status, "insufficient")
        self.assertTrue(all(not row.strong for row in current.rows))

    def test_scope_keeps_printed_identifiers_without_activity_or_structure(self):
        self.assertIsNone(
            source_exclusion("8A", "Compound 8A", ["unverified_source_structure"])
        )
        self.assertIsNone(source_exclusion("I-255"))
        self.assertEqual(source_exclusion(""), "unconfirmed_identifier")
        self.assertEqual(
            source_exclusion("编号待确认 S0498", "source-structure:x"),
            "unconfirmed_identifier",
        )
        self.assertEqual(source_exclusion("中间体 12"), "intermediate")
        self.assertEqual(source_exclusion("Intermediate18"), "intermediate")
        self.assertEqual(source_exclusion("Intermediate_18"), "intermediate")

    def test_explicit_missing_number_markers_are_not_compound_identifiers(self):
        for label in (
            "-",
            "--",
            "—",
            "–",
            "N/A",
            "n/a",
            "NaN",
            "None",
            "null",
            "undefined",
            "unnumbered",
            "unassigned",
            "无编号",
            "未编号",
            "编号缺失",
            "编号待定",
            "  N/A  ",
        ):
            with self.subTest(label=label):
                self.assertEqual(source_exclusion(label), "unconfirmed_identifier")
        # Missing-marker detection is exact, never a guessed numbering grammar.
        for label in ("8", "8A", "8B", "I-255", "Example 12", "NA-1", "A", "0"):
            with self.subTest(label=label):
                self.assertIsNone(source_exclusion(label))

    def test_historical_missing_number_markers_do_not_enter_counts_or_anchor(self):
        packet, captured = self.historical(["0.1"] * 9 + ["10", "100", "1000", ""])
        original = copy.deepcopy(packet)
        for index, label in enumerate(("-", "N/A")):
            packet["molecules"][index]["label"] = label
            captured.rows[index].label = label
        archive = copy.deepcopy(captured.model_dump())
        current, excluded = current_report(packet, captured, [])
        self.assertEqual(current.molecule_count, 11)
        self.assertEqual(current.policies[0].strength_scale.strong_boundary, 10000)
        self.assertEqual(excluded, {"unconfirmed_identifier": 2})
        self.assertFalse({"-", "N/A"}.intersection(row.label for row in current.rows))
        self.assertEqual(
            sum(item.molecules for item in current.distributions[0].bins), 11
        )
        self.assertEqual(captured.model_dump(), archive)
        self.assertEqual(len(packet["molecules"]), len(original["molecules"]))

    def test_identical_replay_is_read_only_while_new_work_stays_cleanup_blocked(self):
        request = AnalysisRequest(
            request_id="a" * 32,
            expected_dataset_revision=1,
            region_id="b" * 32,
            metric_id="IC50",
            direction="lower",
        )
        queue = Mock(retained_lease=True, recovery_blocked=True)
        published = Mock(id="published")
        queue.jobs.existing.return_value = published
        queue.view.return_value = published
        value, _ = existing(queue, "dataset", request)
        self.assertIs(value, published)
        queue.view.assert_called_once_with("published")
        queue.service.store.connect.assert_not_called()
        queue.jobs.existing.return_value = None
        with self.assertRaises(WebError) as rejected:
            existing(queue, "dataset", request)
        self.assertEqual(rejected.exception.code, "sar_process_unverified")
        queue.service.store.connect.assert_not_called()


class CurrentStrengthAPITests(WebFixture, unittest.TestCase):
    dataset = support.SARAPITests.dataset

    def test_csv_placeholder_numbers_are_excluded_before_paging_and_empty_pool_rejected(
        self,
    ):
        with self.client() as client:
            markers = ("-", "N/A", "NaN", "None", "未编号", "Intermediate 1")
            source = "id,smiles,IC50 (nM),assay\n" + "".join(
                f"{label},CO,0.000001,binding\n" for label in markers
            )
            dataset = self.dataset(
                client, (source + "I-255,CCO,,binding\n8B,,9,binding\n").encode()
            )
            self.assertEqual((dataset["input_row_count"], dataset["row_count"]), (8, 2))
            path = support.ROOT + "/datasets/" + dataset["id"] + "/molecules"
            rows = client.get(path).json()
            self.assertEqual({row["label"] for row in rows["items"]}, {"I-255", "8B"})
            self.assertEqual(
                client.get(path + "?page=2&page_size=1").json()["total"], 2
            )
            preview = client.post(
                support.ROOT + "/csv/preview?filename=numberless.csv",
                content=source.encode(),
                headers={"Content-Type": "text/csv"},
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            rejected = client.post(
                support.ROOT + "/datasets/csv",
                json={
                    "token": preview.json()["token"],
                    "title": "No numbered compounds",
                    "id_column": "id",
                    "smiles_column": "smiles",
                    "activity_columns": ["IC50 (nM)"],
                    "assay_column": "assay",
                    "request_id": uuid.uuid4().hex,
                },
            )
            self.assertEqual(rejected.status_code, 422, rejected.text)
            self.assertEqual(
                rejected.json()["error"]["code"], "sar_numbered_pool_empty"
            )

    def test_csv_scope_retains_identified_missing_measurements_and_excludes_blank_or_intermediate(
        self,
    ):
        with self.client() as client:
            data = b"id,smiles,IC50 (nM),assay\nS1,CO,1,binding\n,CCO,0.0001,binding\nIntermediate 3,CCCO,0.0001,binding\nI-255,CCCO,,binding\n8B,,9,binding\n"
            dataset = self.dataset(client, data)
            self.assertEqual((dataset["input_row_count"], dataset["row_count"]), (5, 3))
            path = support.ROOT + "/datasets/" + dataset["id"] + "/molecules"
            rows = client.get(path).json()
            self.assertEqual(
                {row["label"] for row in rows["items"]}, {"S1", "I-255", "8B"}
            )
            self.assertEqual(
                client.get(path + "?page=2&page_size=1").json()["total"], 3
            )
            self.assertEqual(
                len(client.get(path + "?page=2&page_size=1").json()["items"]), 1
            )

    def test_native_historical_api_view_filter_and_export_share_the_current_scope(self):
        # A native old-policy worker fixture, published only to this private test state.
        fixture = study_support.StudyAnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        values = ["0.1"] * 9 + ["1", "10", "100", ""]
        rows = [
            molecule(f"S{index + 1}", "COc1ccc(Cl)cc1", value)
            for index, value in enumerate(values)
        ]
        # A legacy import may contain a placeholder with otherwise valid chemistry.
        # Scope cannot rely only on historical issues/eligibility flags.
        unknown = molecule("unconfirmed", "CO", "0.000001")
        unknown.update(label="N/A")
        nonfinal = molecule("nonfinal", "CO", "0.0000001")
        nonfinal.update(label="Compound 42", source_compound_id=" Intermediates 2 ")
        packet = fixture.packet(
            rows=[*rows, unknown, nonfinal],
            regions=1,
            policies=[policy(strong_threshold=1.0)],
        )
        reply, captured = fixture.run_packet(packet)
        with self.client() as client:
            service, queue = client.app.state.sar, client.app.state.sar_queue
            service.datasets.publish(
                Dataset.model_validate(packet["dataset"]),
                [Molecule.model_validate(row) for row in packet["molecules"]],
                uuid.uuid4().hex,
                "a" * 64,
            )
            root = service.assets.area("results") / packet["job_id"]
            shutil.copytree(fixture.root, root)
            job = SARJob(
                id=packet["job_id"],
                dataset_id=packet["dataset"]["id"],
                region_id=packet["regions"][0]["id"],
                metric_id="activity",
                kind="study",
                status="complete",
                total=len(packet["molecules"]) + captured.strict_pair_count,
                processed=len(packet["molecules"]) + captured.strict_pair_count,
                created_at=packet["dataset"]["created_at"],
                input_sha256=digest(packet),
            )
            queue.jobs.create(
                job,
                uuid.uuid4().hex,
                "b" * 64,
                {
                    "engine_sha256": packet["engine_sha256"],
                    "report_sha256": reply["report_sha256"],
                    "attempt_id": uuid.uuid4().hex,
                    "kind": "study",
                    "request": packet["request"],
                },
                str(root),
            )
            recorded_pairs = [
                pair
                for index in range(reply["chunks"])
                for pair in json.loads((root / f"chunk-{index:04d}.json").read_text())[
                    "pairs"
                ]
            ]
            with service.store.connect(write=True) as connection:
                connection.executemany(
                    "INSERT INTO pairs VALUES(?,?,?)",
                    [
                        (job.id, ordinal, encode(pair))
                        for ordinal, pair in enumerate(recorded_pairs)
                    ],
                )
            original_bytes = (root / "report.json").read_bytes()
            path = support.ROOT + "/jobs/" + job.id + "/study"
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            view = response.json()
            self.assertEqual(view["activity_basis"]["anchor_rank"], 10)
            self.assertEqual(
                view["activity_basis"]["excluded_records"],
                {"unconfirmed_identifier": 1, "intermediate": 1},
            )
            self.assertEqual(view["report"]["molecule_count"], 13)
            scale = view["report"]["policies"][0]["strength_scale"]
            self.assertEqual(
                (scale["strong_boundary"], scale["medium_boundary"]), (10, 100)
            )
            self.assertEqual(
                client.get(path + "/rows?scope=strong&page_size=2").json()["total"], 10
            )
            self.assertEqual(
                client.get(path + "/rows?page=2&page_size=2").json()["total"], 13
            )
            self.assertEqual(
                client.get(
                    support.ROOT + "/jobs/" + job.id + "/pairs?page_size=2"
                ).json()["total"],
                12,
            )
            full = client.get(path + "/export?format=json").json()
            self.assertEqual(full["report"], captured.model_dump())
            self.assertEqual(full["activity_view"]["report"]["molecule_count"], 13)
            self.assertNotIn(
                "unconfirmed", client.get(path + "/export?format=csv").text
            )
            self.assertNotIn("nonfinal", client.get(path + "/export?format=csv").text)
            self.assertEqual((root / "report.json").read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
