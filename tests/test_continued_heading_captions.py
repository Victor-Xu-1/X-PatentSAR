"""Borrowed headers cannot become new local catalogue-title observations."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fitz
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.artifact_catalog import expand_shared_json, pack_shared_json
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_column_captions import column_caption_boxes
from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from tests import test_lateral_column_continuation as continuation_fixture


class ContinuedHeadingCaptionTests(unittest.TestCase):
    def test_borrowed_header_never_asks_for_original_header_context(self):
        for kind in ("continued_ruled_columns", "continued_unruled_columns"):
            with (
                self.subTest(kind=kind),
                patch(
                    "patent_sar_extractor.core.heading_column_captions.original_column_context",
                    side_effect=AssertionError("A continuation owns no new header"),
                ),
                patch(
                    "patent_sar_extractor.core.heading_column_captions.catalog_for_scope",
                    return_value=SimpleNamespace(identifier="TABLE11"),
                ),
            ):
                self.assertEqual(
                    column_caption_boxes({"kind": kind}, {"lines": []}), []
                )

    def test_original_header_context_still_must_be_qualified(self):
        for kind in (None, "original_ruled_columns"):
            with (
                self.subTest(kind=kind),
                patch(
                    "patent_sar_extractor.core.heading_column_captions.original_column_context",
                    side_effect=ValueError("Unqualified original source"),
                ),
                patch(
                    "patent_sar_extractor.core.heading_column_captions.catalog_for_scope",
                    return_value=SimpleNamespace(identifier="TABLE11"),
                ),
                self.assertRaisesRegex(ValueError, "Unqualified original source"),
            ):
                column_caption_boxes({"kind": kind}, {"lines": []})


class ContinuedHeadingSourceTests(LateralStructureControls, unittest.TestCase):
    def observed_control(self):
        _, payload = self.run_case(
            mutate_document=lambda d, r: (
                continuation_fixture.LateralColumnContinuationTests.continued_tables(
                    self, d, r, prior_right_experiment=True, continued_columns=(0,)
                )
            )
        )
        return payload

    @staticmethod
    def heading_record(payload):
        return next(
            row
            for row in payload["compound_catalog"]["entries"]
            if row["cpd"] == "Compound B80"
        )

    def test_shared_serialization_keeps_the_proved_later_row_inventory(self):
        payload = self.observed_control()
        restored = expand_shared_json(json.loads(json.dumps(pack_shared_json(payload))))
        self.assertEqual(restored, payload)
        self.assertEqual(coverage_errors(restored), [])
        record = self.heading_record(restored)
        self.assertEqual(record["structure_id"], "INDEPENDENT-B80")
        self.assertFalse(annotate_binding_accuracy(record)["fail_closed"])
        scope = record["original_heading_structure_evidence"]["declaration_scope"]
        self.assertEqual(len(scope["pages"][1]["structures"]), 2)
        self.assertEqual(len(scope["later_columns"][0]["sources"][0]["cells"]), 2)

    def test_either_column_and_different_identifiers_use_the_same_source_proof(self):
        for column, identifier in ((0, "007C"), (1, "J17A")):
            with self.subTest(column=column, identifier=identifier):
                _, payload = self.run_case(
                    mutate_document=lambda d, r, column=column, identifier=identifier: (
                        continuation_fixture.LateralColumnContinuationTests.continued_tables(
                            self,
                            d,
                            r,
                            prior_right_experiment=True,
                            prior_experiment_column=column,
                            heading_identifier=identifier,
                            continued_columns=(1 - column,),
                        )
                    )
                )
                record = next(
                    row
                    for row in payload["compound_catalog"]["entries"]
                    if row["cpd"] == f"Compound {identifier}"
                )
                self.assertEqual(record["structure_id"], f"INDEPENDENT-{identifier}")
                self.assertEqual(coverage_errors(payload), [])

    def test_original_replay_checks_anchor_and_current_rows_without_ocr(self):
        record = self.heading_record(self.observed_control())
        for changed_page in (None, 0, 1):
            with (
                self.subTest(changed_page=changed_page),
                fitz.open(self.root / "original.pdf") as original,
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=AssertionError("Source replay must not recognize"),
                ),
            ):
                if changed_page is not None:
                    box = (
                        fitz.Rect(44, 71, 75, 82)
                        if changed_page == 0
                        else fitz.Rect(50, 140, 75, 160)
                    )
                    original[changed_page].draw_rect(box, color=None, fill=(0, 0, 0))
                errors = original_heading_source_errors(original, [record])
                if changed_page is None:
                    self.assertEqual(errors, [])
                else:
                    self.assertTrue(errors)

    def test_missing_unread_foreign_or_changed_later_proof_cannot_exclude_drawings(
        self,
    ):
        source = self.heading_record(self.observed_control())
        for mutation in (
            "missing_cell",
            "unread_cell",
            "missing_observation",
            "foreign_region",
            "foreign_original",
            "invented_caption",
            "omitted_diagram",
        ):
            changed = copy.deepcopy(source)
            scope = changed["original_heading_structure_evidence"]["declaration_scope"]
            witness = scope["later_columns"][0]["sources"][0]
            if mutation == "missing_cell":
                witness["cells"].pop()
            elif mutation == "unread_cell":
                witness["cells"][0]["needs_review"] = True
            elif mutation == "missing_observation":
                witness["cells"][0]["observations"] = []
            elif mutation == "foreign_region":
                witness["section"]["region_id"] = "0" * 64
            elif mutation == "foreign_original":
                witness["section"]["source"]["header_scope"]["original_pdf_sha256"] = (
                    "0" * 64
                )
            elif mutation == "invented_caption":
                witness["caption_frames"] = [{"bbox": [1, 2, 3, 4]}]
            else:
                scope["pages"][1]["structures"].pop()
            with self.subTest(mutation=mutation):
                self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])
