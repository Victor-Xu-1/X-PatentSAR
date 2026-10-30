"""A complete non-molecular original grid cannot hide other unknown sources."""

import copy
import unittest

from patent_sar_extractor.core.activity_grid_role_observation import (
    observe_characterization,
)
from patent_sar_extractor.core.declaration_reference_ownership import (
    characterization_owns_catalogue_title,
)
from tests import test_role_grid_coverage as controls


class DeclarationReferenceOwnershipTests(unittest.TestCase):
    def original(self, *, last_text=None):
        fixture = controls.RoleGridCoverageTests()
        self.addCleanup(fixture.doCleanups)
        page, grid, tokens, _identifiers = fixture.original(2, last_text=last_text)
        role = observe_characterization(page, grid, tokens, "")
        box = [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]]
        original = {
            "page_no": 1,
            "bbox": box,
            "role": "unresolved",
            "diagrams": [],
            "unproved_title": True,
            "unproved_nonfinal_role": False,
        }
        source = {"page_no": 1, "page_grids": [grid]}
        regions = [{"page_no": 1, "bbox": box, "role_scope": role}]
        return original, source, regions

    def test_complete_native_role_owns_only_its_identical_physical_grid(self):
        original, source, regions = self.original()
        self.assertIsNotNone(regions[0]["role_scope"])
        self.assertTrue(
            characterization_owns_catalogue_title(original, source, regions)
        )
        self.assertEqual(original["role"], "unresolved")
        self.assertTrue(original["unproved_title"])  # No source observation rewritten.

    def test_measurement_or_unknown_last_cell_cannot_borrow_characterization(self):
        for text in (
            "1H NMR (400 MHz); IC50 = 3 nM",
            "Unclassified original observation",
        ):
            with self.subTest(text=text):
                original, source, regions = self.original(last_text=text)
                self.assertIsNone(regions[0]["role_scope"])
                self.assertFalse(
                    characterization_owns_catalogue_title(original, source, regions)
                )

    def test_missing_foreign_partial_duplicate_and_changed_grid_refuse(self):
        original, source, regions = self.original()
        for mode in (
            "missing",
            "foreign",
            "partial",
            "duplicate",
            "changed_grid",
            "duplicate_grid",
            "boolean_page",
            "changed_role",
        ):
            current, page, references = (
                copy.deepcopy(original),
                copy.deepcopy(source),
                copy.deepcopy(regions),
            )
            if mode == "missing":
                references.clear()
            elif mode == "foreign":
                references[0]["page_no"] = 2
            elif mode == "partial":
                references[0]["bbox"][3] -= 18
            elif mode == "duplicate":
                references.append(copy.deepcopy(references[0]))
            elif mode == "changed_grid":
                page["page_grids"][0]["ys"][1] += 1
            elif mode == "duplicate_grid":
                page["page_grids"].append(copy.deepcopy(page["page_grids"][0]))
            elif mode == "boolean_page":
                page["page_no"] = True
            else:
                references[0]["role_scope"]["observations"][0]["matrix"][-1][-1] = (
                    "IC50 = 3 nM"
                )
            with self.subTest(mode=mode):
                self.assertFalse(
                    characterization_owns_catalogue_title(current, page, references)
                )

    def test_diagram_or_explicit_nonfinal_conflict_keeps_its_title_obligation(self):
        original, source, regions = self.original()
        for mode in ("diagram", "nonfinal", "unknown_shape", "foreign_declaration"):
            current = copy.deepcopy(original)
            if mode == "diagram":
                current["diagrams"] = [
                    {"id": "generated-drawing", "bbox": current["bbox"]}
                ]
            elif mode == "nonfinal":
                current["unproved_nonfinal_role"] = True
            elif mode == "unknown_shape":
                current.pop("unproved_nonfinal_role")
            else:
                current["page_no"] = 2
            with self.subTest(mode=mode):
                self.assertFalse(
                    characterization_owns_catalogue_title(current, source, regions)
                )
