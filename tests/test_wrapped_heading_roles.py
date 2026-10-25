"""Physical role qualifiers cannot disappear before terminal-product admission."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.heading_detector_identity import detector_conflicts
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import heading_observation_status
from patent_sar_extractor.core.source_section_roles import (
    nonfinal_original_label,
    section_body_boundary,
    section_heading,
)


class WrappedHeadingRoleTests(unittest.TestCase):
    @staticmethod
    def document(lines, *, leading=20, second_x=40, font="helv"):
        document = fitz.open()
        page = document.new_page(width=600, height=600)
        for index, text in enumerate(lines):
            page.insert_text(
                (40 if index == 0 else second_x, 65 + index * leading),
                text,
                fontsize=11,
                fontname=font,
            )
        return document

    @staticmethod
    def observe(document):
        sections = []
        with patch(
            "patent_sar_extractor.core.heading_observation.get_ocr_engine",
            side_effect=AssertionError("This regression must not invoke a model"),
        ):
            blocks = observed_heading_blocks(
                document,
                [0],
                {},
                source_sections=sections,
                source_regions={0: []},
                grids_for_page=lambda _page: [],
            )
        return blocks, sections

    def test_literal_prefix_and_original_number_share_one_role(self):
        for prefix, label, role in (
            ("Intermediate", "Compound Q-03", "intermediate_section"),
            ("Preparation of intermediate", "Example Z-007B", "intermediate_section"),
            ("Biological evaluation", "Example Q-03", "assay_section"),
            ("Biological evaluation", "Compound Q-03", "assay_section"),
        ):
            raw = f"{prefix}\n{label}"
            with self.subTest(raw=raw):
                observed = section_heading(raw)
                self.assertIsNotNone(observed)
                self.assertEqual(observed["role"], role)
                self.assertEqual(observed["line_text"], raw)
                self.assertTrue(nonfinal_original_label(raw))
                if role == "assay_section":
                    self.assertEqual(section_body_boundary(raw), observed)

    def test_line_breaks_and_existing_paragraph_locators_do_not_change_role(self):
        for raw in (
            "Intermediate Compound Q-03",
            "[0042] Intermediate\nCompound Q-03",
            "Biological evaluation Example Q-03",
            "［００４２］ Biological evaluation\nExample Q-03",
        ):
            with self.subTest(raw=raw):
                observed = section_heading(raw)
                self.assertIsNotNone(observed)
                self.assertNotEqual(observed["role"], "compound_heading")
                self.assertEqual(observed["identifier"], "Q-03")
                self.assertEqual(observed["line_text"], raw)

    def test_nearby_native_prefix_is_not_dropped_before_ocsr_selection(self):
        for leading in (18, 20, 24):
            for prefix, label, role in (
                ("Intermediate", "Compound Q-03", "intermediate_section"),
                ("Intermediates", "Compounds Q-03 and R-04", "intermediate_section"),
                ("Biological evaluation", "Example Q-03", "assay_section"),
            ):
                with self.subTest(leading=leading, prefix=prefix):
                    with self.document([prefix, label], leading=leading) as document:
                        blocks, sections = self.observe(document)
                    self.assertEqual(blocks, [])
                    self.assertEqual(len(sections), 1)
                    self.assertEqual(sections[0]["role"], role)
                    self.assertEqual(sections[0]["status"], "confirmed")
                    self.assertEqual(
                        [
                            row["text"]
                            for row in sections[0]["heading_observation"]["nomination"][
                                "rows"
                            ]
                        ],
                        [prefix, label],
                    )
                    self.assertEqual(
                        reference_issues(
                            {
                                "source_sections": sections,
                                "source_reference_scope": reference_scope(sections),
                            },
                            [],
                        ),
                        [],
                    )

    def test_chinese_original_role_rows_use_the_same_physical_proof(self):
        for prefix, label, role in (
            ("中间体", "化合物 73", "intermediate_section"),
            ("生物评价", "实施例 73", "assay_section"),
        ):
            with (
                self.subTest(prefix=prefix),
                self.document([prefix, label], font="china-s") as document,
            ):
                blocks, sections = self.observe(document)
                self.assertEqual(blocks, [])
                self.assertEqual(sections[0]["role"], role)
                proof = sections[0]["heading_observation"]
                self.assertEqual(heading_observation_status(proof)[0], "confirmed")
                validate_original_heading(document[0], proof)

    def test_orphan_or_other_column_prefix_remains_an_explicit_source_gap(self):
        for leading, second_x in ((70, 40), (20, 330)):
            for prefix in ("Intermediate", "Biological evaluation"):
                with self.subTest(leading=leading, second_x=second_x, prefix=prefix):
                    with self.document(
                        [prefix, "Compound Q-03"], leading=leading, second_x=second_x
                    ) as document:
                        _blocks, sections = self.observe(document)
                    issues = reference_issues(
                        {
                            "source_sections": sections,
                            "source_reference_scope": reference_scope(sections),
                        },
                        [],
                    )
                    self.assertTrue(
                        any(
                            issue["reason"] == "unproved_original_heading"
                            for issue in issues
                        )
                    )
                    self.assertTrue(
                        any(section["line_text"] == prefix for section in sections)
                    )

    def test_prose_reference_and_identifier_namespace_do_not_supply_a_role(self):
        for first in (
            "An intermediate was consumed.",
            "Biological evaluation was not performed.",
        ):
            with self.subTest(first=first):
                with self.document([first, "Compound I-255"], leading=24) as document:
                    blocks, sections = self.observe(document)
                self.assertEqual([block["cpd"] for block in blocks], ["Compound I-255"])
                self.assertEqual(len(sections), 1)
                self.assertEqual(sections[0]["role"], "compound_heading")

    def test_non_numbered_section_title_does_not_invent_a_missing_molecule(self):
        for prefix in ("Intermediate", "Biological evaluation"):
            with self.subTest(prefix=prefix):
                with self.document(
                    [prefix, "The procedure was performed."]
                ) as document:
                    blocks, sections = self.observe(document)
                self.assertEqual(blocks, [])
                self.assertEqual(sections, [])

    def test_assay_prefix_does_not_erase_an_explicit_synthesis_conflict(self):
        raw = "Biological evaluation\nSynthesis of Compound Q-03"
        observed = section_heading(raw)
        self.assertIsNotNone(observed)
        self.assertEqual(observed["role"], "ambiguous_heading")
        self.assertTrue(nonfinal_original_label(raw))

    def test_detector_fragments_retain_the_complete_original_role(self):
        for raw in (
            "Intermediate\nCompound Q-03",
            "Biological evaluation\nExample Q-03",
        ):
            with self.subTest(raw=raw):
                declaration = section_heading(raw)
                self.assertIsNotNone(declaration)
                parts = [
                    {
                        "text": text,
                        "confidence": 0.99,
                        "bbox": [
                            [0, index * 20],
                            [180, index * 20],
                            [180, index * 20 + 10],
                            [0, index * 20 + 10],
                        ],
                    }
                    for index, text in enumerate(raw.splitlines())
                ]
                reading = {"raw_text": raw, "detection_parts": parts}
                self.assertFalse(detector_conflicts([reading], declaration))
                parts[-1] = {**parts[-1], "text": "Compound R-04"}
                self.assertTrue(detector_conflicts([reading], declaration))
                parts[-1] = {**parts[-1], "text": "Compound Q-03: Synthesis"}
                self.assertTrue(detector_conflicts([reading], declaration))
                parts[-1] = {**parts[-1], "confidence_valid": False}
                self.assertTrue(detector_conflicts([reading], declaration))

    def test_serialized_proof_cannot_drop_or_change_its_original_role_row(self):
        with self.document(["Intermediate", "Compound Q-03"]) as document:
            _blocks, sections = self.observe(document)
            saved = json.loads(json.dumps(sections[0]["heading_observation"]))
            self.assertEqual(heading_observation_status(saved)[0], "confirmed")
            validate_original_heading(document[0], saved)
            for field in ("text", "rows", "native"):
                changed = copy.deepcopy(saved)
                if field == "text":
                    changed["nomination"]["text"] = "Compound Q-03"
                elif field == "rows":
                    changed["nomination"]["rows"] = changed["nomination"]["rows"][1:]
                else:
                    changed["native_source"]["text"] = "Compound Q-03"
                with self.subTest(field=field):
                    self.assertNotEqual(
                        heading_observation_status(changed)[0], "confirmed"
                    )
            document[0].insert_text((40, 65), "Biological evaluation", fontsize=11)
            with self.assertRaises(ValueError):
                validate_original_heading(document[0], saved)


if __name__ == "__main__":
    unittest.main()
