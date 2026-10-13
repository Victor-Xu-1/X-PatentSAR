"""Complete source-page accounting is independent of molecular correctness."""

import copy
import unittest

from patent_sar_extractor.core.structure_inventory import (
    inventory_packet,
    validate_structure_inventory,
)


class StructureInventoryTests(unittest.TestCase):
    def payload(self):
        return {
            "total_structures": 1,
            "structures": [{"structure_id": "S0", "page_no": 2}],
            "source_inventory": inventory_packet(
                3,
                [
                    {
                        "page_no": 1,
                        "status": "detected",
                        "scope": "full_page",
                        "candidates": 0,
                    },
                    {
                        "page_no": 2,
                        "status": "detected",
                        "scope": "full_page",
                        "candidates": 1,
                    },
                    {
                        "page_no": 3,
                        "status": "detected",
                        "scope": "full_page",
                        "candidates": 0,
                    },
                ],
            ),
        }

    def test_zero_detection_is_recorded_without_inventing_a_structure(self):
        value = self.payload()
        validate_structure_inventory(value, expected_pages=[0, 1, 2], page_count=3)
        self.assertEqual(len(value["structures"]), 1)

    def test_missing_duplicate_failed_partial_and_miscounted_pages_reject(self):
        for kind in (
            "missing",
            "duplicate",
            "failed",
            "partial",
            "count",
            "foreign",
            "old",
        ):
            with self.subTest(kind=kind):
                value = copy.deepcopy(self.payload())
                pages = value["source_inventory"]["pages"]
                if kind == "missing":
                    pages.pop()
                elif kind == "duplicate":
                    pages.append(pages[0])
                elif kind == "failed":
                    pages[0]["status"] = "failed"
                elif kind == "partial":
                    pages[0]["scope"] = "region"
                elif kind == "count":
                    pages[1]["candidates"] = 2
                elif kind == "foreign":
                    value["structures"][0]["page_no"] = 4
                else:
                    value.pop("source_inventory")
                with self.assertRaises(ValueError):
                    validate_structure_inventory(
                        value, expected_pages=[0, 1, 2], page_count=3
                    )

    def test_chunk_is_not_mistaken_for_complete_document(self):
        value = self.payload()
        value["source_inventory"]["pages"] = value["source_inventory"]["pages"][1:2]
        validate_structure_inventory(value, expected_pages=[1], page_count=3)
        with self.assertRaises(ValueError):
            validate_structure_inventory(value, full_document=True)

    def test_outside_boolean_or_duplicate_request_is_rejected(self):
        for pages in ([0, 1, 3], [False, 1, 2], [0, 1, 1]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                validate_structure_inventory(self.payload(), expected_pages=pages)
