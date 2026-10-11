"""Bounded current-group preparation without duplicate DTO copies."""

import json
import unittest
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_sar_api as support
import test_sar_study_api as study_support
from test_web_support import WebFixture

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.models import Region
from patent_sar_extractor.web.sar.study_current import _small_view
from patent_sar_extractor.web.sar.study_models import (
    StudyFragment,
    StudyRegionSummary,
    StudyScaffold,
)
from patent_sar_extractor.web.sar.study_results import StudyResults
from patent_sar_extractor.web.sar.study_view import current_records, current_report
from patent_sar_extractor.web.sar.study_view_groups import GroupBins, current_groups


def bin_domain():
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
    return domain


class CountedKeys(OrderedDict):
    scans = 0

    def __iter__(self):
        self.scans += 1
        return super().__iter__()


def fragment(identifier, members, reference=False):
    return StudyFragment(
        id=identifier,
        smiles="[*:1]C",
        molecule_ids=members,
        molecule_count=len(members),
        strong_count=0,
        bins=[],
        better=0,
        worse=0,
        indeterminate=0,
        missing=0,
        is_reference=reference,
    )


def group_report():
    region = Region(
        id="variable",
        dataset_id="dataset",
        molecule_id="A",
        dataset_revision=1,
        graph_sha256="a" * 64,
        atom_indices=[0],
        attachment_count=1,
        created_at="2026-01-01T00:00:00Z",
    )
    summary = StudyRegionSummary(
        region=region,
        reference_label="A",
        reference_fragment_id="reference",
        fixed_background_sha256="b" * 64,
        matched=2,
        not_matched=1,
        ambiguous=0,
        ineligible=0,
        comparable=1,
        no_variation=False,
        fragments=[fragment("reference", ["A"], True), fragment("change", ["B", "C"])],
        comparison_pool=["B", "C", "D"],
    )
    scaffold = StudyScaffold(
        id="core",
        smiles="C",
        molecule_ids=["A", "B", "C", "D"],
        molecule_count=4,
        strong_count=0,
        bins=[],
    )
    pairs = [
        {
            "region_id": "variable",
            "molecule_id": identifier,
            "fragment_id": "change" if status == "matched" else None,
            "match_status": status,
            "comparison": outcome,
        }
        for identifier, status, outcome in (
            ("B", "matched", "better"),
            ("C", "matched", "indeterminate"),
            ("D", "not_matched", "missing"),
        )
    ]
    return SimpleNamespace(scaffolds=[scaffold], regions=[summary]), pairs


class ViewGroupTests(unittest.TestCase):
    def test_capacity_checks_do_not_rescan_unrelated_cached_members(self):
        cache = GroupBins(bin_domain())
        cache._items = CountedKeys()
        for index in range(300):
            cache.for_members([str(index)])
        self.assertEqual(cache._items.scans, 0)
        self.assertEqual(len(cache._items), 256)

    def test_lru_member_budget_and_oversized_bypass_preserve_fresh_results(self):
        domain = bin_domain()
        cache = GroupBins(domain)
        first = cache.for_members(["B", "A"])
        first[0].molecules = 999
        second = cache.for_members(["A", "B"])
        self.assertEqual(second[0].molecules, 2)
        self.assertIsNot(first, second)
        self.assertIsNot(first[0], second[0])
        self.assertEqual(domain.for_members.call_count, 1)
        cache.for_members([f"first-{i}" for i in range(3000)])
        cache.for_members([f"second-{i}" for i in range(3000)])
        self.assertEqual(sum(map(len, cache._items)), 3000)
        cache.for_members([str(i) for i in range(4097)])
        self.assertEqual(sum(map(len, cache._items)), 3000)
        cache.for_members(["new"])
        self.assertEqual(sum(map(len, cache._items)), 3001)
        self.assertEqual(cache._member_references, 3001)
        self.assertLessEqual(len(cache._items), 256)

    def test_each_kept_fragment_has_one_independent_projection_copy(self):
        report, pairs = group_report()
        original = report.regions[0].model_dump()
        calls = []
        copy_model = StudyFragment.model_copy

        def counted(item, **kwargs):
            calls.append(item.id)
            return copy_model(item, **kwargs)

        with patch.object(StudyFragment, "model_copy", counted):
            scaffolds, regions = current_groups(
                report,
                {"A", "B", "C", "D"},
                bin_domain(),
                {mid: {"strong": mid == "B"} for mid in ("A", "B", "C", "D")},
                pairs,
            )
        self.assertEqual(calls, ["reference", "change"])
        self.assertEqual(scaffolds[0].strong_count, 1)
        self.assertEqual(regions[0].comparable, 1)
        changed = regions[0].fragments[1]
        self.assertEqual(
            (changed.better, changed.worse, changed.indeterminate), (1, 0, 1)
        )
        self.assertEqual((changed.molecule_count, changed.strong_count), (2, 1))
        changed.molecule_ids.append("modified result only")
        changed.bins[0].molecules = 99
        self.assertEqual(report.regions[0].model_dump(), original)

    def test_excluded_members_and_empty_fragments_never_receive_a_dto_copy(self):
        report, pairs = group_report()
        calls = []
        copy_model = StudyFragment.model_copy

        def counted(item, **kwargs):
            calls.append(item.id)
            return copy_model(item, **kwargs)

        with patch.object(StudyFragment, "model_copy", counted):
            scaffolds, regions = current_groups(
                report,
                {"A", "D"},
                bin_domain(),
                {"A": {"strong": False}, "D": {"strong": False}},
                pairs,
            )
        self.assertEqual(calls, ["reference"])
        self.assertEqual(scaffolds[0].molecule_ids, ["A", "D"])
        self.assertEqual(regions[0].comparison_pool, ["D"])
        self.assertEqual((regions[0].matched, regions[0].not_matched), (0, 1))
        self.assertTrue(regions[0].no_variation)

    def test_missing_or_duplicate_comparison_coverage_still_refuses(self):
        report, pairs = group_report()
        for bad in (pairs[:-1], pairs + pairs[:1]):
            with self.subTest(pairs=len(bad)), self.assertRaises(WebError) as caught:
                current_groups(
                    report,
                    {"A", "B", "C", "D"},
                    bin_domain(),
                    {mid: {"strong": False} for mid in ("A", "B", "C", "D")},
                    bad,
                )
            self.assertEqual(caught.exception.code, "sar_report_scope")


class RowProjectionTests(WebFixture, unittest.TestCase):
    dataset = support.SARAPITests.dataset
    region = support.SARAPITests.region
    completed = support.SARAPITests.completed
    start = study_support.SARStudyAPITests.start

    def test_paged_rows_do_not_rebuild_unrelated_group_charts(self):
        with self.client() as client:
            source = (
                b"id,smiles,IC50 (nM),assay\n"
                b"I-12,COc1ccc(Cl)cc1,1,binding\n"
                b"8B,CCOc1ccc(Cl)cc1,10,binding\n"
                b"Example 3,CCOc1ccc(Br)cc1,100,binding\n"
            )
            dataset = self.dataset(client, source)
            region = self.region(client, dataset)
            job, _ = self.start(client, dataset, [region["id"]])
            job = self.completed(client, job)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            overview = client.get(path).json()["report"]
            fragment_id = overview["regions"][0]["fragments"][0]["id"]
            selectors = (
                "?page_size=1&page=2",
                "?scope=strong",
                "?scope=leads",
                "?scaffold_id=" + overview["scaffolds"][0]["id"],
                "?region_id=" + region["id"] + "&fragment_id=" + fragment_id,
            )
            expected = [
                client.get(path + "/rows" + selector).json() for selector in selectors
            ]
            candidate = next(
                mid
                for item in overview["regions"][0]["fragments"]
                for mid in item["molecule_ids"]
                if mid != region["molecule_id"]
            )
            preview_path = (
                path
                + "/preview?region_id="
                + region["id"]
                + "&molecule_id="
                + candidate
            )
            expected_preview = client.get(preview_path).json()
            with patch.object(
                GroupBins,
                "for_members",
                side_effect=AssertionError("row read rebuilt unrelated chart DTOs"),
            ):
                for selector, body in zip(selectors, expected, strict=True):
                    # Cold small reads must obey the same preparation contract as
                    # large reports, which are never retained in this cache.
                    _small_view.cache_clear()
                    response = client.get(path + "/rows" + selector)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json(), body)
                _small_view.cache_clear()
                preview = client.get(preview_path)
                self.assertEqual(preview.status_code, 200, preview.text)
                self.assertEqual(preview.json(), expected_preview)

            # Count-preserving corruption is still refused; returning one page
            # cannot skip complete region-pool verification.
            with client.app.state.sar.store.connect(write=True) as connection:
                saved = connection.execute(
                    "SELECT ordinal,payload FROM pairs WHERE job_id=? ORDER BY ordinal LIMIT 1",
                    (job["id"],),
                ).fetchone()
                changed = json.loads(saved["payload"])
                changed["molecule_id"] = region["molecule_id"]
                connection.execute(
                    "UPDATE pairs SET payload=? WHERE job_id=? AND ordinal=?",
                    (json.dumps(changed), job["id"], saved["ordinal"]),
                )
            rejected = client.get(path + "/rows?page_size=1")
            self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertEqual(rejected.json()["error"]["code"], "sar_report_scope")

    def test_source_excluded_fragment_cannot_be_selected_from_a_row_view(self):
        report, _ = group_report()
        projected = Mock(
            molecule_ids={"A", "D"},
            regions=report.regions,
            scaffolds=report.scaffolds,
            rows=[],
            policies=[],
        )
        reader = StudyResults(Mock())
        reader.load = Mock(return_value=(Mock(), report))
        with (
            patch(
                "patent_sar_extractor.web.sar.study_current.projected",
                return_value=(projected, {}),
            ),
            self.assertRaises(WebError) as caught,
        ):
            reader.rows("job", region_id="variable", fragment_id="change")
        self.assertEqual(caught.exception.code, "sar_study_filter")

    def test_rows_and_full_view_share_the_same_source_and_tenth_dose_authority(self):
        import test_sar_study_analysis as native

        fixture = native.StudyAnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        rows = [
            native.molecule(f"R{index}", "COc1ccc(Cl)cc1", value)
            for index, value in enumerate(["0.1"] * 9 + ["1", "10", "100", ""])
        ]
        packet = fixture.packet(rows=rows, regions=1, policies=[native.policy()])
        reply, captured = fixture.run_packet(packet)
        packet["molecules"][1]["label"] = "N/A"
        captured.rows[1].label = "N/A"
        pairs = [
            pair
            for index in range(reply["chunks"])
            for pair in json.loads(
                (fixture.root / f"chunk-{index:04d}.json").read_text()
            )["pairs"]
        ]
        original = captured.model_dump()
        view, exclusions = current_records(packet, captured, pairs)
        full, expected = current_report(packet, captured, pairs)
        self.assertEqual(exclusions, expected)
        self.assertEqual(exclusions, {"unconfirmed_identifier": 1})
        self.assertEqual(
            [row.model_dump() for row in view.rows],
            [row.model_dump() for row in full.rows],
        )
        self.assertEqual(
            [row.model_dump() for row in view.policies],
            [row.model_dump() for row in full.policies],
        )
        self.assertEqual(view.molecule_count, full.molecule_count)
        self.assertEqual(captured.model_dump(), original)


if __name__ == "__main__":
    unittest.main()
