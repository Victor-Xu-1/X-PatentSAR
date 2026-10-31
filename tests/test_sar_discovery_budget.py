"""Strictly proved duplicate plans cannot consume the retained-comparison budget."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_sar_discovery import source
from test_sar_site_reduction import plan

from patent_sar_extractor.core.sar.discovery import comparison_plan, discover_sites
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.prepared_graphs import GraphPool
from patent_sar_extractor.core.sar.site_reduction import compact_proved_sites


class DiscoveryBudgetTests(unittest.TestCase):
    def test_exact_retained_budget_keeps_all_centres_sites_and_original_order(self):
        cases = (
            ("COc1ccc(Cl)cc1", "CCOc1ccc(Cl)cc1"),
            ("CCCOc1ccc(Cl)cc1", "CCCCOc1ccc(Cl)cc1"),
            ("COc1ccc(Cl)cc1", "CCOc1ccc(Cl)cc1", "CCCOc1ccc(Cl)cc1"),
        )
        dataset = {"id": "generated-budget-control", "revision": 1}
        for smiles in cases:
            rows = [source(str(i + 1), value) for i, value in enumerate(smiles)]
            expected, coverage = discover_sites(rows, dataset)
            self.assertGreater(coverage["redundant_proved_sites"], 0)
            with self.subTest(
                molecules=len(rows), comparisons=coverage["candidate_comparisons"]
            ):
                result = discover_sites(
                    rows, dataset, pair_budget=coverage["candidate_comparisons"]
                )
                self.assertEqual(result, (expected, coverage))
                self.assertEqual(
                    discover_sites(
                        list(reversed(rows)),
                        dataset,
                        pair_budget=coverage["candidate_comparisons"],
                    ),
                    result,
                )

    def test_less_than_the_complete_retained_plan_refuses_without_partial_results(self):
        rows = [source("1", "COc1ccc(Cl)cc1"), source("2", "CCOc1ccc(Cl)cc1")]
        dataset = {"id": "generated-budget-control", "revision": 1}
        _sites, coverage = discover_sites(rows, dataset)
        with self.assertRaises(SARInputError) as raised:
            discover_sites(
                rows, dataset, pair_budget=coverage["candidate_comparisons"] - 1
            )
        self.assertEqual(raised.exception.code, "study_discovery_pair_limit")

    def test_stream_stops_before_materializing_the_rest_of_an_over_budget_matrix(self):
        consumed = []

        def proposals():
            for number in range(1000):
                consumed.append(number)
                yield plan(f"site-{number:04d}", [5])

        with self.assertRaises(SARInputError):
            compact_proved_sites(
                proposals(),
                [],
                GraphPool(),
                lambda: None,
                pair_budget=2,
                site_budget=4096,
            )
        self.assertEqual(consumed, [0, 1, 2])

    def test_strict_duplicate_proof_is_reused_without_spending_more_pair_slots(self):
        rows = [source("1", "COc1ccccc1Cl"), source("2", "COc1ccncc1Cl")]
        plans = [
            plan("small", [5]),
            plan("larger", [4, 5, 6]),
            plan("largest", [3, 4, 5, 6]),
        ]
        matcher = compile_reference(rows[0]["molfile"], [5])
        compare = Mock(wraps=matcher.compare)
        with patch(
            "patent_sar_extractor.core.sar.site_reduction.compile_reference",
            return_value=SimpleNamespace(compare=compare),
        ) as compile_call:
            kept, removed = compact_proved_sites(
                iter(plans),
                rows,
                GraphPool(),
                lambda: None,
                pair_budget=1,
                site_budget=1,
            )
            self.assertEqual((kept, removed), ([plans[0]], 2))
            self.assertEqual(compile_call.call_count, 1)
            self.assertEqual(compare.call_count, 1)

    def test_index_only_narrower_site_cannot_hide_a_valid_broader_comparison(self):
        rows = [source("1", "COc1ccccc1Cl"), source("2", "COc1cnccc1Cl")]
        plans = [plan("small", [5]), plan("larger", [4, 5, 6])]
        with self.assertRaises(SARInputError):
            compact_proved_sites(
                iter(plans),
                rows,
                GraphPool(),
                lambda: None,
                pair_budget=1,
            )
        self.assertEqual(
            compact_proved_sites(
                iter(plans),
                rows,
                GraphPool(),
                lambda: None,
                pair_budget=2,
            ),
            (plans, 0),
        )

    def test_out_of_order_stream_refuses_instead_of_using_an_unsound_retained_count(
        self,
    ):
        with self.assertRaises(ValueError):
            compact_proved_sites(
                iter([plan("large", [4, 5, 6]), plan("small", [5])]),
                [],
                GraphPool(),
                lambda: None,
            )

    def test_invalid_budget_is_rejected_before_any_chemical_work(self):
        from patent_sar_extractor.core.sar import discovery

        with patch.object(
            discovery,
            "read_molfile",
            side_effect=AssertionError("Invalid budget cannot parse chemistry"),
        ):
            for value in (-1, True, 1.0, discovery.MAX_PAIRS + 1):
                with self.subTest(value=value), self.assertRaises(SARInputError):
                    discover_sites(
                        [], {"id": "generated", "revision": 1}, pair_budget=value
                    )

    def test_same_graphs_can_finish_with_zero_comparisons_and_no_invented_sites(self):
        rows = [source("1", "COc1ccc(Cl)cc1"), source("2", "COc1ccc(Cl)cc1")]
        sites, coverage = discover_sites(
            rows, {"id": "generated", "revision": 1}, pair_budget=0
        )
        self.assertEqual(sites, [])
        self.assertEqual(coverage["candidate_comparisons"], 0)

    def test_original_cut_boundary_and_site_limits_still_refuse_without_truncation(
        self,
    ):
        rows = [source("1", "COc1ccc(Cl)cc1"), source("2", "CCOc1ccc(Cl)cc1")]
        for limit, code in (
            ("MAX_CUTS", "study_discovery_cut_limit"),
            ("MAX_BOUNDARIES", "study_discovery_boundary_limit"),
            ("MAX_SITES", "study_discovery_pair_limit"),
        ):
            with (
                self.subTest(limit=limit),
                patch("patent_sar_extractor.core.sar.discovery." + limit, 0),
            ):
                with self.assertRaises(SARInputError) as raised:
                    discover_sites(rows, {"id": "generated", "revision": 1})
                self.assertEqual(raised.exception.code, code)

    def test_manual_sites_reserve_their_comparisons_and_keep_original_identity(self):
        rows = [source("1", "COc1ccc(Cl)cc1"), source("2", "CCOc1ccc(Cl)cc1")]
        dataset = {"id": "generated-manual-budget", "revision": 1}
        automatic, _ = discover_sites(rows, dataset)
        manual = {**automatic[0]["region"], "id": "manual", "name": "Original site"}
        request = {"discover_single_sites": True}
        expected = comparison_plan(rows, [manual], dataset, request, lambda: None)
        required = sum(len(plan["candidate_ids"]) for plan in expected[0])
        with patch("patent_sar_extractor.core.sar.discovery.MAX_PAIRS", required):
            self.assertEqual(
                comparison_plan(rows, [manual], dataset, request, lambda: None),
                expected,
            )
        self.assertEqual(expected[0][0]["region"], manual)
        self.assertEqual(expected[0][0]["origin"], "manual")
        self.assertTrue(all(plan["region"] != manual for plan in expected[0][1:]))
        with (
            patch("patent_sar_extractor.core.sar.discovery.MAX_PAIRS", required - 1),
            self.assertRaises(SARInputError),
        ):
            comparison_plan(rows, [manual], dataset, request, lambda: None)

    def test_cancel_during_original_order_preflight_stops_without_a_partial_plan(self):
        rows = [source("1", "COc1ccc(Cl)cc1"), source("2", "CCOc1ccc(Cl)cc1")]
        cancelled = False

        def check():
            if cancelled:
                raise TimeoutError("controlled cancellation")

        def prepare(*args, **kwargs):
            nonlocal cancelled
            result = compile_reference(*args, **kwargs)
            cancelled = True
            return result

        with (
            patch(
                "patent_sar_extractor.core.sar.site_plans.compile_reference",
                side_effect=prepare,
            ) as compiled,
            self.assertRaisesRegex(TimeoutError, "controlled cancellation"),
        ):
            discover_sites(rows, {"id": "generated", "revision": 1}, check=check)
        self.assertEqual(compiled.call_count, 1)


if __name__ == "__main__":
    unittest.main()
