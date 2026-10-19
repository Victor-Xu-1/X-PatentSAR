"""Literal numbered-cell recovery with original pixels, never a private patent."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.cell_identity_proof import confirmed_identity_readings
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.source_section_roles import heading_members
from patent_sar_extractor.core.table_cells import read_cell
from patent_sar_extractor.core.text_ocr.cell_proof import replay_auxiliary_cell
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary, primary


class AuxiliaryIdentifierTests(unittest.TestCase):
    def scanned(self, literal):
        with fitz.open() as source:
            page = source.new_page(width=300, height=140)
            page.insert_text((25, 45), literal, fontsize=10)
            pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png")
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=300, height=140)
        page.insert_image(page.rect, stream=pixels)
        return page

    def read(self, literal, *, kind="id", texts=None, engine=primary, tokens=()):
        page = self.scanned(literal)
        reader = ControlledAuxiliary(texts or (literal,))
        with (
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=reader,
                create=True,
            ),
        ):
            result = read_cell(page, (15, 25, 265, 60), list(tokens), kind, False)
        return page, reader, result

    def test_unread_differing_ids_recover_only_from_two_complete_literal_views(self):
        for literal, expected, kind in (
            ("027B", "027B", "id"),
            ("I-205", "I-205", "id"),
            ("Compound 41A", "41A", "label"),
            ("Example 08", "08", "label"),
        ):
            with self.subTest(literal=literal):
                page, reader, reading = self.read(literal, kind=kind)
                self.assertEqual(reading.value, expected)
                self.assertFalse(reading.needs_review)
                self.assertEqual(reader.calls, 2)
                self.assertTrue(
                    confirmed_identity_readings(
                        expected, reading.observations, caption=kind == "label"
                    )
                )
                restored = json.loads(json.dumps(reading.observations))
                for observation in restored[-2:]:
                    self.assertEqual(observation["raw_text"], literal)
                    self.assertEqual(
                        observation["auxiliary_text"]["views"][0]["primary"][
                            "raw_text"
                        ],
                        "weak",
                    )
                    self.assertTrue(replay_auxiliary_cell(observation, page))

    def test_primary_valid_ids_do_not_invoke_auxiliary(self):
        def good(image, *, use_det, use_cls):
            return ([], None) if use_det else ([["027B", 0.999]], None)

        _, reader, reading = self.read("027B", engine=good)
        self.assertEqual(reading.value, "027B")
        self.assertFalse(reading.needs_review)
        self.assertEqual(reader.calls, 0)

    def test_qualified_page_identifier_cannot_be_overwritten_by_auxiliary_pair(self):
        tokens = [{"text": "Compound 42A", "x": 70, "y": 40, "bbox": [25, 32, 120, 48]}]
        _, _, reading = self.read("Compound 41A", kind="label", tokens=tokens)
        self.assertEqual(reading.value, "")
        self.assertTrue(reading.needs_review)

    def test_valid_disagreement_in_primary_views_stays_unresolved_without_model_call(
        self,
    ):
        texts = iter(("41A", "41B"))

        def disagree(image, *, use_det, use_cls):
            return ([], None) if use_det else ([[next(texts), 0.999]], None)

        _, reader, reading = self.read("41A", engine=disagree)
        self.assertEqual(reading.value, "")
        self.assertTrue(reading.needs_review)
        self.assertEqual(reader.calls, 0)

    def test_weak_primary_nonfinal_role_is_not_erased(self):
        def nonfinal(image, *, use_det, use_cls):
            return ([], None) if use_det else ([["Intermediate 41A", 0.2]], None)

        _, _, reading = self.read("Compound 41A", kind="label", engine=nonfinal)
        self.assertEqual(reading.value, "")
        self.assertTrue(reading.needs_review)

    def test_disagreement_extra_annotation_and_nonfinal_are_not_repaired(self):
        for texts in (("027B", "027C"), ("027B note",), ("Intermediate 027B",)):
            with self.subTest(texts=texts):
                _, _, reading = self.read("027B", texts=texts)
                self.assertEqual(reading.value, "")
                self.assertTrue(reading.needs_review)

    def test_saved_packet_removal_or_primary_change_cannot_qualify_identifier(self):
        _, _, reading = self.read("Compound 41A", kind="label")
        self.assertEqual(reading.value, "41A")
        for field in ("packet", "both_markers", "primary"):
            observations = copy.deepcopy(reading.observations)
            if field in {"packet", "both_markers"}:
                observations[-1].pop("auxiliary_text")
                if field == "both_markers":
                    observations[-1].pop("physical_header_lines")
            else:
                observations[-1]["auxiliary_text"]["views"][0]["primary"][
                    "raw_text"
                ] = "Compound 41B"
            self.assertFalse(
                confirmed_identity_readings("41A", observations, caption=True), field
            )

    def test_scanned_synthesis_heading_uses_same_literal_pair_and_original_replay(self):
        page = self.scanned("Example 027B")
        reader = ControlledAuxiliary(("Example 027B",))
        line = {
            "text": "Example 279",
            "bbox": [20, 32, 120, 50],
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        with (
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", primary),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=reader,
                create=True,
            ),
        ):
            proof = observe_heading(page, line, "a" * 64, grids=[])
        self.assertEqual(proof["status"], "confirmed", proof)
        self.assertEqual(heading_members(proved_heading_declaration(proof)), ["027B"])
        self.assertEqual(reader.calls, 2)
        validate_original_heading(page, json.loads(json.dumps(proof)))
        page.insert_text((80, 45), "note", fontsize=7)
        with self.assertRaises(ValueError):
            validate_original_heading(page, proof)

    @unittest.skipUnless(
        os.environ.get("PATENTSAR_TEST_TEXT_OCR_PYTHON")
        and os.environ.get("PATENTSAR_TEST_TEXT_OCR_MODELS"),
        "Explicit existing runtime/model required; controlled source only",
    )
    def test_native_model_reads_generated_numbered_sources_through_shared_cell(self):
        from patent_sar_extractor.core.text_ocr.runtime import AuxiliaryTextRuntime

        with (
            tempfile.TemporaryDirectory() as directory,
            AuxiliaryTextRuntime(
                Path(os.environ["PATENTSAR_TEST_TEXT_OCR_PYTHON"]),
                Path(os.environ["PATENTSAR_TEST_TEXT_OCR_MODELS"]),
                Path(directory),
            ) as reader,
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", primary),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=reader,
            ),
        ):
            for literal, label in (("Compound 27B", "27B"), ("Example 73", "73")):
                with self.subTest(literal=literal):
                    page = self.scanned(literal)
                    reading = read_cell(page, (15, 25, 265, 60), [], "label", False)
                    self.assertEqual(reading.value, label, reading.observations)
                    self.assertFalse(reading.needs_review)
                    self.assertTrue(
                        confirmed_identity_readings(
                            label, reading.observations, caption=True
                        )
                    )
                    self.assertTrue(
                        replay_auxiliary_cell(reading.observations[-1], page)
                    )
            process = reader.worker_process
        self.assertIsNotNone(process.poll())
