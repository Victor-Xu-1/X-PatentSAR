"""Original title typography cannot erase or invert source catalogue roles."""

import copy
import json
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_semantics import catalog_title_role
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_table_roles import observed_role
from tests import test_caption_role_writer as writer_controls
from tests.test_caption_role_continuation import binding, two_pages
from tests.test_caption_role_raster import raster_catalog
from tests.test_caption_source_roles import catalog


class CaptionTitleSpacingTests(unittest.TestCase):
    def test_known_negative_title_is_not_outvoted_by_an_unqualified_reading(self):
        doc, structures, boxes = catalog("Table 63.NotCompounds", prefixed=True)
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        proposal = next(
            item["evidence"]["proposal"]
            for item in result.issues
            if item.get("evidence", {}).get("proposal", {}).get("caption_role")
        )
        packet = proposal["caption_role"]["observations"][0]
        weak = copy.deepcopy(packet)
        weak.update(origin="raster", status="unqualified")
        for token in weak["tokens"]:
            token.update(source="raster", confidence=0.4)
        self.assertEqual(observed_role([packet, weak]), ("conflict", ""))

    def test_case_delimited_original_roles_preserve_categories_and_negation(self):
        for title, expected in (
            ("Table 63.CompoundsTable", "compound"),
            ("Table 74.IntermediateCompounds", "nonfinal"),
            ("Table 85.CompoundsAndIntermediates", "mixed"),
            ("Table 96.TargetProducts", "compound"),
            ("Table 108.Non-LimitingCompounds", "compound"),
            ("Table 119.NotCompoundsTable", "conflict"),
            ("Table 130. Not Compounds", "conflict"),
            ("Table 141. No intermediates", "conflict"),
            ("Table 152.Compoundsomething", "unknown"),
            ("Table 163.CompoundingTable", "unknown"),
            ("Table 174.NotSelectedCompounds", "compound"),
            ("Table 185.NotLimitedToCompounds", "compound"),
            ("Table 196.NonFinalCompounds", "conflict"),
            ("Table 207.Compounds not Intermediates", "conflict"),
            ("Table 218.NoStartingMaterials", "conflict"),
        ):
            with self.subTest(title=title):
                self.assertEqual(catalog_title_role(title), expected)

    def test_native_caption_role_reaches_the_same_formal_gate_above_and_below(self):
        for below in (False, True):
            with self.subTest(below=below):
                doc, structures, boxes = catalog(
                    "Table 63.CompoundsTable", prefixed=True, below=below
                )
                with (
                    doc,
                    patch(
                        "patent_sar_extractor.core.table_cells.get_ocr_engine",
                        side_effect=AssertionError("Native control must not load OCR"),
                    ),
                ):
                    observed = bind_caption_grids(doc, structures, boxes, [1])
                self.assertEqual(
                    [item["label"] for item in observed.bindings], ["I-004A", "I-009B"]
                )
                for item in observed.bindings:
                    saved = json.loads(json.dumps(binding(item)))
                    self.assertTrue(valid_caption_binding_evidence(saved))
                    self.assertEqual(
                        item["ownership"]["caption_role"]["role"], "compound"
                    )
                    self.assertEqual(
                        item["ownership"]["caption_role"]["observations"][0]["text"],
                        "Table 63.CompoundsTable",
                    )

    def test_source_role_stays_complete_across_ordinary_and_split_page_tables(self):
        for split in (False, True):
            with self.subTest(split=split):
                doc, structures, boxes, grids, pages = two_pages(
                    split=split, first_title="Table 63.CompoundsTable"
                )
                with doc:
                    observed = bind_caption_grids(
                        doc,
                        structures,
                        boxes,
                        pages,
                        grids_for_page=lambda page, grids=grids: grids.get(
                            page.number + 1, []
                        ),
                    )
                expected = {"41A", "89B", "73C", "104D"}
                if split:
                    expected |= {"7E", "8E"}
                self.assertEqual(
                    {item["label"] for item in observed.bindings},
                    expected,
                    [item["reason"] for item in observed.issues],
                )
                for item in observed.bindings:
                    self.assertTrue(
                        valid_caption_binding_evidence(
                            json.loads(json.dumps(binding(item)))
                        )
                    )

    def test_negative_and_mixed_titles_veto_while_unknown_keeps_existing_caption_policy(
        self,
    ):
        for title in (
            "Table 63.NotCompounds",
            "Table 74.NoIntermediates",
            "Table 85.CompoundsAndIntermediates",
            "Table 96.Compoundsomething",
        ):
            for prefixed in (False, True):
                with self.subTest(title=title, prefixed=prefixed):
                    doc, structures, boxes = catalog(title, prefixed=prefixed)
                    with doc:
                        observed = bind_caption_grids(doc, structures, boxes, [1])
                    if title.endswith("Compoundsomething") and prefixed:
                        # An unknown title does not override explicit original
                        # Compound labels; it cannot grant bare-ID admission.
                        self.assertEqual(len(observed.bindings), 2)
                    else:
                        self.assertEqual(observed.bindings, [])
                        self.assertTrue(observed.issues)
                    self.assertEqual(observed.exclusions, [])

    def test_existing_raster_engine_preserves_dense_spaceless_catalogue_ownership(self):
        labels = ("17B", "172", "902AB")
        doc, structures, boxes = raster_catalog(
            "Table 63.CompoundsTable",
            prefixed=True,
            labels=labels,
            label_height=14,
            label_fontname="hebo",
        )
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual(
            [pair["label"] for pair in result.bindings],
            list(labels),
            [issue["reason"] for issue in result.issues],
        )
        self.assertEqual(result.issues, [])
        for pair in result.bindings:
            saved = json.loads(json.dumps(binding(pair)))
            self.assertTrue(valid_caption_binding_evidence(saved))
            self.assertEqual(pair["ownership"]["caption_role"]["role"], "compound")
            changed = copy.deepcopy(saved)
            changed["exact_caption_evidence"]["ownership"]["caption_role"]["role"] = (
                "unknown"
            )
            self.assertFalse(valid_caption_binding_evidence(changed))

    def test_case_delimited_nonfinal_catalogue_is_retained_not_published(self):
        for title in (
            "Table 63.IntermediateCompounds",
            "Table 74.StartingMaterials",
            "Table 85.BuildingBlocks",
        ):
            with self.subTest(title=title):
                doc, structures, boxes = catalog(title, prefixed=True)
                with doc:
                    result = bind_caption_grids(doc, structures, boxes, [1])
                self.assertEqual(result.bindings, [])
                self.assertEqual(len(result.exclusions), 1)
                self.assertEqual(
                    result.exclusions[0]["caption_role"]["role"], "nonfinal"
                )

    def test_complete_native_binder_writer_and_reader_preserve_split_page_owners(self):
        control = writer_controls.CaptionRoleWriterTests()
        self.addCleanup(control.doCleanups)
        doc, structures, boxes, _grids, _pages = two_pages(
            split=True, first_title="Table 63.CompoundsTable"
        )
        payload, records = control.execute_document(doc, structures, boxes)
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        entries, _aliases = read_catalog_entries(
            payload, {record["structure_id"] for record in records}
        )
        self.assertEqual(
            {row["cpd"] for row in entries},
            {
                "Compound 41A",
                "Compound 89B",
                "Compound 7E",
                "Compound 8E",
                "Compound 73C",
                "Compound 104D",
            },
        )


if __name__ == "__main__":
    unittest.main()
