"""Whole source regions include open original rows and every accepted grid row."""

import copy
import hashlib
import json
import unittest
from contextlib import nullcontext

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.binding_source_references import (
    _regions,
    reference_scope,
)
from patent_sar_extractor.core.binding_source_regions import (
    identifier_references,
    reference_regions,
)
from patent_sar_extractor.core.source_evidence_identity import (
    SourceEvidenceLimit,
    proof_id,
)
from patent_sar_extractor.core.source_grid_edges import edge_intervals
from patent_sar_extractor.core.source_role_fragments import validate_fragments
from tests import test_role_grid_coverage as grid_controls
from tests import test_source_grid_fragments as fragment_controls


class RoleOriginalBoundaryTests(unittest.TestCase):
    def test_raster_open_row_uses_existing_full_frames_without_mutating_saved_sources(
        self,
    ):
        with fragment_controls.split_row() as original, fitz.open() as document:
            for page in original:
                raster = document.new_page(
                    width=page.rect.width, height=page.rect.height
                )
                raster.insert_image(
                    raster.rect,
                    stream=page.get_pixmap(
                        matrix=fitz.Matrix(3, 3), alpha=False
                    ).tobytes("png"),
                )
            _blocks, payload, regions = fragment_controls.observe(document)
            before = copy.deepcopy(payload)
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                [],
            )
            self.assertEqual(payload, before)
            source = regions[0]["row_fragments"][0]["source_cells"]
            source["rendered_frames"][0][0]["pixel_sha256"] = "f" * 64
            validate_fragments(regions[0])
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                )
            )

    def test_open_original_row_cannot_disappear_from_role_source_readback(self):
        with fragment_controls.split_row() as document:
            _blocks, payload, regions = fragment_controls.observe(document)
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                [],
            )
            bottom = regions[0]["row_fragments"][0]["bbox"]
            document[0].insert_text(
                (bottom[0] + 8, bottom[1] + 50), "Compound 999", fontsize=6
            )
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(document)
                ),
                "Changed open row is outside the closed grid but still part of original role evidence",
            )

    def test_original_edge_inventory_uses_the_same_whole_grid_bound(self):
        fixture = grid_controls.RoleGridCoverageTests()
        self.addCleanup(fixture.doCleanups)
        for count in (96, 120):
            with self.subTest(count=count):
                page, grid, tokens, identifiers = fixture.original(count)
                regions = reference_regions(
                    page, original_pdf_sha256="a" * 64, grids=[grid], tokens=tokens
                )
                self.assertEqual(len(regions), 1)
                region = regions[0]
                record = {k: v for k, v in region.items() if k != "region_id"}
                encoded = json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                self.assertEqual(
                    region["region_id"], hashlib.sha256(encoded).hexdigest()
                )
                if count == 120:
                    self.assertGreater(len(encoded), 1024 * 1024)
                    with self.assertRaises(SourceEvidenceLimit):
                        proof_id(record)
                section = {
                    "role": "characterization_region",
                    "page_no": 1,
                    "source_region": region,
                }
                scope = reference_scope([section], original_pdf_sha256="a" * 64)
                self.assertEqual(
                    _regions([section], scope), {region["region_id"]: region}
                )
                self.assertEqual(
                    [item["identifier"] for item in identifier_references(regions[0])],
                    identifiers,
                )

    def test_whole_grid_bound_does_not_admit_huge_or_malformed_edge_sources(self):
        packet = {
            "version": 1,
            "page_size": [50, 5000],
            "xs": [0, 10, 20],
            "ys": [10, 20],
            "vertical_rules": [],
            "rule_frame": None,
        }
        self.assertEqual(edge_intervals(packet), [])
        for field, value in (
            ("ys", list(range(2050))),
            ("xs", [0, True, 20]),
            ("page_size", [50, 10**400]),
            ("ys", [0, float("nan")]),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                edge_intervals({**packet, field: value})
