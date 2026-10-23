"""Raw locator numbers never compete with an already proved physical caption."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.binding_original_replay import (
    original_binding_source_errors,
    original_binding_sources,
)
from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.caption_label_roles import ROLE, caption_label_index
from patent_sar_extractor.core.caption_locator_source import observe_caption_locator
from patent_sar_extractor.core.ocsr.candidate_inputs import load_source_observation_plan
from patent_sar_extractor.core.ocsr.recognition_inputs import (
    RecognitionPlan,
    recognition_inputs,
)
from patent_sar_extractor.core.source_evidence_identity import SourceEvidenceLimit
from tests import test_candidate_observations as candidates
from tests import test_heading_label_roles as fixtures


class CaptionLocatorOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.primary = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError(
                    "No OCR construction for a proved original cell"
                ),
            )
        )
        fixture = fixtures.HeadingLabelRoleTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.source, _result, self.payload = fixture.run_binding()
        self.parent = next(
            entry
            for entry in self.payload["compound_catalog"]["entries"]
            if entry["cpd"] == "Compound 17"
        )
        self.reference = next(
            source
            for source in self.payload["source_sections"]
            if source["role"] == ROLE and source["identifier"] == "17"
        )
        self.line = {
            "text": "Compound 1",  # A deliberately clipped locator, not a read.
            "bbox": self.reference["bbox"],
            "source": "page_ocr",
            "geometry_space": "rendered",
            "y0": self.reference["bbox"][1],
            "y1": self.reference["bbox"][3],
        }

    def tearDown(self):
        self.assertEqual(self.primary.call_count, 0)

    def observe(self, line=None, bindings=None):
        sections = []
        with (
            fitz.open(self.source) as document,
            patch(
                "patent_sar_extractor.core.binding_source_headings.original_heading_lines",
                return_value=[line or self.line],
            ),
        ):
            blocks = observed_heading_blocks(
                document,
                [0],
                {},
                source_sections=sections,
                source_bindings=bindings
                if bindings is not None
                else self.payload["compound_catalog"]["entries"],
            )
        return blocks, sections

    def test_a_clipped_page_locator_is_one_source_not_an_extra_synthesis_heading(self):
        before = copy.deepcopy(self.payload)
        blocks, sections = self.observe()
        self.assertEqual(blocks, [])
        references = [section for section in sections if section["role"] == ROLE]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["line_text"], "Compound 1")
        self.assertEqual(references[0]["identifier"], "17")
        self.assertIn("physical_source", references[0])
        self.assertEqual(self.payload, before)

    def test_native_or_separate_original_occurrences_cannot_borrow_a_caption(self):
        with fitz.open(self.source) as document:
            separate = list(document[0].search_for("Compound 19: Preparation")[0])
        for line in (
            {**self.line, "source": "native"},
            {**self.line, "bbox": separate, "y0": separate[1], "y1": separate[3]},
        ):
            with self.subTest(line=line):
                _blocks, sections = self.observe(line)
                self.assertFalse(any(section["role"] == ROLE for section in sections))

    def with_reference(self):
        _blocks, sections = self.observe()
        reference = next(section for section in sections if section["role"] == ROLE)
        payload = copy.deepcopy(self.payload)
        payload["source_sections"].append(reference)
        payload["source_reference_scope"] = reference_scope(
            payload["source_sections"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )
        return payload

    def test_same_original_plan_carries_the_reference_without_new_molecule_work(self):
        payload = self.with_reference()
        before, after = recognition_inputs(self.payload), recognition_inputs(payload)
        self.assertEqual(after.work_items, before.work_items)
        self.assertEqual(len(after.caption_references), 1)
        self.assertTrue(
            original_binding_sources([], caption_references=after.caption_references)
        )
        self.assertEqual(
            reference_issues(payload, payload["compound_catalog"]["entries"]), []
        )
        with fitz.open(self.source) as document:
            self.assertEqual(
                original_binding_source_errors(
                    document,
                    after.work_items,
                    role_text=after.role_text,
                    plot_references=after.plot_references,
                    caption_references=after.caption_references,
                ),
                [],
            )

    def test_saved_reference_cannot_rename_its_owner_or_drop_its_physical_proof(self):
        original = self.with_reference()
        for mutation in (
            "identifier",
            "source_key",
            "missing",
            "bounds",
            "size",
            "pixels",
        ):
            payload = copy.deepcopy(original)
            reference = payload["source_sections"][-1]
            if mutation == "identifier":
                reference["identifier"] = "1"
            elif mutation == "source_key":
                reference["source_key"] = "f" * 64
            elif mutation == "missing":
                del reference["physical_source"]
            elif mutation == "bounds":
                reference["bbox"][0] += 200
            elif mutation == "size":
                reference["page_size"][0] = True
            else:
                reference["physical_source"]["pixels"]["readings"][0][
                    "mask_encoding"
                ] = "unknown"
            payload["source_reference_scope"] = reference_scope(
                payload["source_sections"],
                original["source_reference_scope"]["original_pdf_sha256"],
            )
            with (
                self.subTest(mutation=mutation),
                self.assertRaises((ValueError, TypeError)),
            ):
                recognition_inputs(payload)

    def test_well_shaped_but_foreign_pixel_digest_requires_actual_original_replay(self):
        payload = self.with_reference()
        payload["source_sections"][-1]["physical_source"]["pixels"]["readings"][0][
            "pixel_sha256"
        ] = "f" * 64
        payload["source_reference_scope"] = reference_scope(
            payload["source_sections"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )
        plan = recognition_inputs(
            payload
        )  # A digest string is not an original pixel proof.
        with fitz.open(self.source) as document:
            self.assertTrue(
                original_binding_source_errors(
                    document,
                    [],
                    caption_references=plan.caption_references,
                )
            )

    def test_original_pixel_replay_cannot_be_removed_with_the_model_input_filter(self):
        payload = self.with_reference()
        plan = recognition_inputs(payload)
        with fitz.open(self.source) as document:
            reference = plan.caption_references[0]
            box = reference["physical_source"]["cell"]
            document[0].draw_line((box[0] + 4, box[1] + 4), (box[0] + 10, box[1] + 10))
            # Even with no molecule bindings supplied, the physical role owner
            # still requires actual original replay through the existing gate.
            self.assertTrue(
                original_binding_source_errors(
                    document,
                    [],
                    caption_references=plan.caption_references,
                )
            )

    def test_foreign_or_competing_sources_do_not_create_a_physical_exemption(self):
        for mode in ("foreign", "competing"):
            bindings = copy.deepcopy(self.payload["compound_catalog"]["entries"])
            parent = next(entry for entry in bindings if entry["cpd"] == "Compound 17")
            if mode == "foreign":
                parent["source_pdf_sha256"] = "f" * 64
            else:
                bindings.append(
                    {**copy.deepcopy(parent), "structure_id": "other-source"}
                )
            with self.subTest(mode=mode):
                _blocks, sections = self.observe(bindings=bindings)
                self.assertFalse(any(section["role"] == ROLE for section in sections))

    def test_padded_crossing_or_prose_locators_do_not_gain_cell_ownership(self):
        box = self.parent["exact_caption_evidence"]["bbox"]
        for line in (
            {**self.line, "bbox": [box[0] - 2, *self.line["bbox"][1:]]},
            {**self.line, "text": "Compound 1: Preparation"},
        ):
            with self.subTest(line=line):
                _blocks, sections = self.observe(line)
                self.assertFalse(any(section["role"] == ROLE for section in sections))

    def test_actual_worker_entry_cannot_drop_a_required_caption_source_replay(self):
        fixture = candidates.CandidateObservationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        metadata = fixture.root / "metadata.json"
        write_json_atomic(metadata, fixture.metadata)
        write_json_atomic(str(metadata) + ".manifest.json", fixture.manifest)
        references = recognition_inputs(self.with_reference()).caption_references
        proven = RecognitionPlan([fixture.owner], [], [], caption_references=references)
        # All candidate metadata/asset bounds are valid; only the foreign
        # original physical caption distinguishes this from the existing plan.
        with self.assertRaisesRegex(
            ValueError, "Original binding/source replay failed"
        ):
            load_source_observation_plan(
                proven,
                structures_json=metadata,
                pdf_path=fixture.pdf,
                binding_dir=fixture.root,
                binding_pdf_sha256=fixture.original_sha,
            )

    def test_no_parent_or_outside_locator_does_not_repeat_grid_detection(self):
        with (
            fitz.open(self.source) as document,
            patch(
                "patent_sar_extractor.core.caption_locator_source.observe_cell_source",
                side_effect=AssertionError("No unowned original rendering"),
            ),
        ):
            self.assertIsNone(observe_caption_locator(document[0], self.line, {}))

    def test_over_budget_role_proof_refuses_the_whole_alias_without_trimming(self):
        index = caption_label_index(
            self.payload["compound_catalog"]["entries"],
            self.payload["source_reference_scope"]["original_pdf_sha256"],
        )
        with (
            fitz.open(self.source) as document,
            patch(
                "patent_sar_extractor.core.caption_label_roles.proof_id",
                side_effect=SourceEvidenceLimit("Controlled complete-source budget"),
            ),
        ):
            self.assertIsNone(observe_caption_locator(document[0], self.line, index))


if __name__ == "__main__":
    unittest.main()
