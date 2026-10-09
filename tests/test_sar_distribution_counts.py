"""Conservation and consistent comparison domains for real SAR charts."""

import unittest
from decimal import Decimal

from patent_sar_extractor.core.sar.study_statistics import assess, distribution


def data(values, grades=None):
    policy = {"context_id": "c", "direction": "lower", "grade_order": grades or []}
    observations = {
        key: [
            {"metric_id": "m", "value": value, "unit": "nM", "context": {}}
            for value in items
        ]
        for key, items in values.items()
    }
    states = {key: assess(items, policy, True) for key, items in observations.items()}
    return observations, policy, states


class SARDistributionCountsTests(unittest.TestCase):
    def test_structure_only_rows_count_as_missing_molecules_not_fake_observations(self):
        obs, policy, states = data({"one": ["1"], "blank": ["NA"], "structure": []})
        result = distribution(list(obs), obs, policy, states)
        missing = next(
            bucket for bucket in result["bins"] if bucket["kind"] == "missing"
        )
        self.assertEqual(missing["molecules"], 2)
        self.assertEqual(missing["observations"], 1)
        self.assertEqual(sum(bucket["molecules"] for bucket in result["bins"]), 3)
        self.assertEqual(sum(bucket["observations"] for bucket in result["bins"]), 2)

    def test_conflicting_repeats_are_one_unresolved_molecule_not_two_grade_members(
        self,
    ):
        obs, policy, states = data(
            {"repeat": ["A", "B"], "equal": ["A", "A"], "none": []}, ["A", "B"]
        )
        result = distribution(list(obs), obs, policy, states)
        bins = {bucket["label"]: bucket for bucket in result["bins"]}
        self.assertEqual(bins["A"]["observations"], 3)
        self.assertEqual(bins["B"]["observations"], 1)
        self.assertEqual(bins["A"]["molecules"], 1)
        self.assertEqual(bins["B"]["molecules"], 0)
        self.assertEqual(bins["conflicting measurements"]["molecules"], 1)
        self.assertEqual(sum(bucket["molecules"] for bucket in result["bins"]), 3)

    def test_partial_missing_repeat_stays_unresolved_in_molecule_mode(self):
        obs, policy, states = data({"partial": ["1", "NA"]})
        result = distribution(list(obs), obs, policy, states)
        self.assertEqual(sum(bucket["molecules"] for bucket in result["bins"]), 1)
        self.assertEqual(
            next(bucket for bucket in result["bins"] if bucket["kind"] == "unresolved")[
                "molecules"
            ],
            1,
        )
        self.assertEqual(result["missing_molecules"], 0)

    def test_numeric_bins_are_ordered_even_when_source_order_is_not_numeric(self):
        obs, policy, states = data({"high": ["100"], "low": ["1"], "mid": ["25"]})
        bins = [
            bucket
            for bucket in distribution(list(obs), obs, policy, states)["bins"]
            if bucket["kind"] == "numeric"
        ]
        bounds = [Decimal(bucket["label"].split(",")[0].lstrip("[")) for bucket in bins]
        self.assertEqual(bounds, sorted(bounds))
        self.assertEqual(len(bins), 8)

    def test_groups_share_the_full_context_numeric_domain(self):
        obs, policy, states = data({"low": ["0"], "middle": ["10"], "high": ["100"]})
        full = distribution(list(obs), obs, policy, states)
        subset = distribution(["middle"], obs, policy, states)
        self.assertEqual(
            [b["label"] for b in subset["bins"] if b["kind"] == "numeric"],
            [b["label"] for b in full["bins"] if b["kind"] == "numeric"],
        )
        self.assertEqual(sum(b["molecules"] for b in subset["bins"]), 1)
        self.assertEqual(sum(b["observations"] for b in subset["bins"]), 1)

    def test_high_precision_values_do_not_collapse_distinct_bin_boundaries(self):
        obs, policy, states = data(
            {"low": ["1." + "0" * 59 + "1"], "high": ["1." + "0" * 59 + "9"]}
        )
        bins = [
            bucket
            for bucket in distribution(list(obs), obs, policy, states)["bins"]
            if bucket["kind"] == "numeric"
        ]
        bounds = [Decimal(bucket["label"].split(",")[0].lstrip("[")) for bucket in bins]
        self.assertEqual(len(set(bounds)), 8)
        self.assertEqual(sum(b["observations"] for b in bins), 2)


if __name__ == "__main__":
    unittest.main()
