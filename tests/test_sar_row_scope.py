"""Whole-core membership is presentation, not a new matcher or numerical rank."""

import copy
import unittest
from types import SimpleNamespace as Item

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.study_row_scope import selected_members


class StudyRowScopeTests(unittest.TestCase):
    def fixture(self):
        def region(identifier, reference, members):
            return Item(
                region=Item(id=identifier, molecule_id=reference),
                fragments=[
                    Item(
                        id="original",
                        is_reference=True,
                        molecule_ids=[reference, "alias"],
                    ),
                    Item(id="changed", is_reference=False, molecule_ids=members),
                ],
            )

        return Item(
            molecule_ids={"ref", "other", "a", "b", "shared", "alias", "none"},
            scaffolds=[Item(id="core", molecule_ids=["a", "shared"])],
            regions=[
                region("one", "ref", ["a", "shared"]),
                region("two", "ref", ["b", "shared"]),
                region("foreign", "other", ["none"]),
            ],
        )

    def select(self, report, **changes):
        options = {
            "scope": "changes",
            "scaffold_id": "",
            "region_id": "",
            "fragment_id": "",
            "reference_id": "ref",
        }
        return selected_members(report, **{**options, **changes})

    def test_union_of_exact_changed_members_is_unique_and_read_only(self):
        report = self.fixture()
        original = copy.deepcopy(report)
        self.assertEqual(self.select(report), {"a", "b", "shared"})
        self.assertEqual(self.select(report, reference_id="other"), {"none"})
        self.assertEqual(self.select(report, reference_id="none"), set())
        self.assertEqual(report, original)

    def test_original_fragment_alias_is_only_removed_from_change_views(self):
        report = self.fixture()
        self.assertEqual(
            self.select(report, scope="all"), {"ref", "alias", "a", "b", "shared"}
        )
        self.assertEqual(
            self.select(report, region_id="one", fragment_id="original"), set()
        )
        self.assertEqual(
            self.select(report, scope="all", region_id="one", fragment_id="original"),
            {"ref", "alias"},
        )

    def test_site_scaffold_and_fragment_intersect_without_cross_reference_union(self):
        report = self.fixture()
        self.assertEqual(
            self.select(report, scaffold_id="core", region_id="two"), {"shared"}
        )
        self.assertEqual(
            self.select(report, region_id="one", fragment_id="changed"), {"a", "shared"}
        )
        for changes in [
            {"reference_id": "unknown"},
            {"region_id": "foreign"},
            {"scaffold_id": "unknown"},
            {"fragment_id": "changed"},
            {"region_id": "one", "fragment_id": "unknown"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(WebError):
                self.select(report, **changes)

    def test_unrestricted_tables_do_not_accidentally_gain_a_change_filter(self):
        self.assertIsNone(self.select(self.fixture(), scope="all", reference_id=""))


if __name__ == "__main__":
    unittest.main()
