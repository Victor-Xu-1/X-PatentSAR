"""The actual worker source-plan reader checks generated recovered column headers."""

import copy
import hashlib
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.role_text_sources import role_text_cells
from patent_sar_extractor.core.structure_inventory import inventory_packet
from tests import test_column_header_text_recovery as headers
from tests import test_role_original_consumers as workers


class ColumnHeaderConsumerTests(unittest.TestCase):
    def adopt(self, consumer, header, original):
        fixture = consumer.fixture
        fixture.pdf = original
        fixture.original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
        fixture.owner["source_pdf_sha256"] = fixture.original_sha
        fixture.manifest["fingerprint"]["pdf_sha256"] = fixture.original_sha
        fixture.manifest["fingerprint"]["params"]["structure_pages"] = list(range(5))
        fixture.metadata["source_inventory"] = inventory_packet(
            5,
            [
                {
                    "page_no": number,
                    "status": "detected",
                    "scope": "full_page",
                    "candidates": count,
                }
                for number, count in ((1, 1), (2, 1), (3, 0), (4, 0), (5, 0))
            ],
        )
        write_json_atomic(consumer.metadata, fixture.metadata)
        write_json_atomic(str(consumer.metadata) + ".manifest.json", fixture.manifest)
        header.update(page_no=5, original_pdf_sha256=fixture.original_sha)
        consumer.payload = {
            "source_sections": [
                {
                    "role": "structure_column_anchor",
                    "page_no": 5,
                    "source": {"header_scope": header},
                }
            ]
        }

    def source(self):
        consumer = workers.RoleOriginalConsumerTests()
        consumer.setUp()
        self.addCleanup(consumer.doCleanups)
        control = headers.ColumnHeaderTextRecoveryTests()
        self.addCleanup(control.doCleanups)
        page, header, roles, _auxiliary, _runtime, _main = control.observe()
        self.assertIsNotNone(roles)
        original = consumer.fixture.root / "generated-column-header.pdf"
        with fitz.open(consumer.fixture.pdf) as document:
            document.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
            document.save(original)
        self.adopt(consumer, header, original)
        return consumer, header

    def test_worker_replays_recovered_header_without_a_new_recognition_task(self):
        consumer, _header = self.source()
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError("Source plan cannot load OCR"),
        ):
            plan = consumer.load(consumer.payload)
        self.assertEqual(len(plan.proven.role_text), 2)
        self.assertEqual({number for number, _ in plan.proven.role_text}, {5})
        self.assertEqual(len(plan.proven.work_items), 1)
        self.assertEqual(len(plan.work_items), 2)

    def test_changed_original_pixels_refuse_even_with_refreshed_document_identity(self):
        consumer, header = self.source()
        changed = consumer.fixture.root / "changed-generated-column-header.pdf"
        with fitz.open(consumer.fixture.pdf) as document:
            document[4].draw_rect(fitz.Rect(25, 52, 70, 68), fill=(0, 0, 0))
            document.save(changed)
        self.adopt(consumer, header, changed)
        # Self-consistent current document identity cannot authorize old text pixels.
        self.assertEqual(len(tuple(role_text_cells(consumer.payload))), 2)
        with self.assertRaisesRegex(
            ValueError, "Original binding/source replay failed"
        ):
            consumer.load(consumer.payload)

    def test_unknown_header_owners_and_inconsistent_frames_cannot_disappear(self):
        consumer, _header = self.source()
        for fault in ("kind", "missing", "frame", "page"):
            with self.subTest(fault=fault):
                changed = copy.deepcopy(consumer.payload)
                header = changed["source_sections"][0]["source"]["header_scope"]
                if fault == "kind":
                    header["kind"] = []
                elif fault == "missing":
                    header.pop("role_cells")
                elif fault == "frame":
                    header["role_cells"]["rendered_frames"][0][0]["pixel_sha256"] = (
                        "c" * 64
                    )
                else:
                    header["page_no"] = 6
                with self.assertRaises((ValueError, TypeError)):
                    consumer.load(changed)
