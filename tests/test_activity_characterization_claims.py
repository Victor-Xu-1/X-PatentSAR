"""A spectral data cell owns a negative role, never an activity measurement.

All images are authored here. Controlled literal readers exercise the real
capture/proof code without starting an OCR runtime or reading a private patent.
"""

import copy
import unittest
from contextlib import nullcontext
from dataclasses import asdict
from unittest.mock import patch

import fitz

from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core import activity_grid_role_observation as role_capture
from patent_sar_extractor.core import activity_text_capture, cell_raster
from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_coverage import coverage_packet, source_record
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from patent_sar_extractor.core.activity_grid_roles import characterization_roles
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.core.activity_text_sources import (
    text_line_qualified,
    text_page_qualified,
)
from patent_sar_extractor.core.source_geometry import (
    SourceTokens,
    native_cell_text,
    source_layout,
)
from patent_sar_extractor.core.source_page_lines import (
    native_page_lines,
    observed_page_text,
)
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions
from tests.test_activity_spatial_roles import ruled

PREFIX = "Table A. Compound characterization"
RESULT = "Table B. Target: JAK; Assay: binding\nNo. | IC50 (nM)\n31 | 9"


class CharacterizationClaimTests(unittest.TestCase):
    def setUp(self):
        self.primary = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError("No native OCR construction"),
            )
        )
        self.auxiliary = self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                side_effect=AssertionError("Known disagreements cannot request a vote"),
            )
        )

    def tearDown(self):
        self.assertEqual(self.primary.call_count, 0)
        self.assertEqual(self.auxiliary.call_count, 0)

    def fixture(self, *, different="spectral", weak=False):
        authored = fitz.open()
        self.addCleanup(authored.close)
        original = authored.new_page(width=600, height=360)
        original.insert_text((30, 40), PREFIX, fontsize=9)
        ruled(
            original,
            [30, 130, 330, 570],
            [60, 90, 160],
            [
                ["Compound No.", "Preparation", "Characterization"],
                [
                    "041B",
                    "Prepared according to Compound 091C",
                    "1H NMR (400 MHz) DMSO 7.0 ppm",
                ],
            ],
        )
        original.insert_text((30, 230), RESULT, fontsize=9)
        native = source_layout(original)
        original_tokens = SourceTokens(native.native, native)
        proposals = native_page_lines(native)
        raw_text = original.get_text("text")
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=600, height=360)
        page.insert_image(
            page.rect,
            stream=original.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png"),
        )
        layout = source_layout(page)
        tokens = SourceTokens(
            [
                {**word, "source": "raster", "confidence": 0.99}
                for word in native.native
            ],
            layout,
            layout.raster_bounds,
        )
        current = {}
        real_render = cell_raster.render_cell_raster

        def render(source, bounds, dpi, **options):
            current.update(text=native_cell_text(original_tokens, bounds), dpi=dpi)
            return real_render(source, bounds, dpi, **options)

        def reader(image, *, use_det, use_cls):
            if use_det:
                return [], None
            text = current["text"]
            if current["dpi"] == 600:
                if different in ("spectral", "swapped_view") or (
                    different == "foreign_cell" and current.get("phase") == "line"
                ):
                    text = text.replace("DMSO", "DMS0")
                elif different == "identifier":
                    text = text.replace("041B", "041D")
                elif different == "preparation":
                    text = text.replace("091C", "091D")
                elif different == "header":
                    text = text.replace("IC50", "DC50")
                elif different == "condition":
                    text = text.replace("JAK", "BET")
                elif different == "value":
                    text = text.replace("31 | 9", "31 | 7")
            if different == "swapped_view" and current.get("phase") == "line":
                text = (
                    text.replace("DMS0", "other")
                    .replace("DMSO", "DMS0")
                    .replace("other", "DMSO")
                )
            return [[text, 0.2 if weak and "DMS" in text else 0.99]], None

        with (
            patch.object(role_capture, "render_cell_raster", render),
            patch.object(activity_text_capture, "render_cell_raster", render),
            patch.object(cell_raster, "render_cell_raster", render),
            patch.object(
                role_capture, "get_ocr_engine", return_value=("rapidocr", reader)
            ),
            patch.object(
                activity_text_capture,
                "get_ocr_engine",
                return_value=("rapidocr", reader),
            ),
        ):
            grid = detect_ruled_table_regions(page, dpi=240)[0]
            proof = role_capture.observe_characterization(page, grid, tokens, PREFIX)
            self.assertIsNotNone(proof)
            region = source_record(
                1,
                "grid",
                [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]],
                "Table A",
                "Compound No. Preparation Characterization",
                "non_activity",
                "observed_characterization",
                0,
                role_scope=proof,
                grid_axes={"xs": list(grid["xs"]), "ys": list(grid["ys"])},
            )
            current["phase"] = "line"
            source = activity_text_capture.capture_text_page(
                page, raw_text, proposals, coordinate_regions=[region]
            )
        return page, region, source

    def payload(self, region, source):
        parsed = extract_text_tables(
            [0],
            {"0": source["nomination_text"]},
            source_reader=lambda _index, _text: source,
            coordinate_regions=[region],
        )
        return {
            **artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
            "coverage": coverage_packet(
                [0],
                [region, *parsed.coverage],
                parsed.rows,
                text_pages=parsed.text_pages,
                text_sources=parsed.text_sources,
            ),
            "rows": [asdict(row) for row in parsed.rows],
            "header_observations": {},
        }

    def test_complete_same_cell_role_keeps_both_reads_and_the_independent_activity(
        self,
    ):
        page, region, source = self.fixture()
        self.assertTrue(valid_role_scope(region))
        spectral = next(
            line for line in source["lines"] if "DMSO" in line["nomination"]
        )
        self.assertFalse(text_line_qualified(spectral))
        self.assertEqual(
            [r["text"] for r in spectral["observations"]],
            [
                "1H NMR (400 MHz) DMSO 7.0 ppm",
                "1H NMR (400 MHz) DMS0 7.0 ppm",
            ],
        )
        self.assertEqual(
            spectral.get("coordinate_owner", {}).get("role"), "characterization"
        )
        before = copy.deepcopy(source)
        payload = self.payload(region, source)
        self.assertEqual(source, before)
        self.assertEqual([row["cpd"] for row in payload["rows"]], ["Compound 31"])
        self.assertFalse(payload["rows"][0]["needs_review"])
        self.assertEqual(payload["rows"][0]["activity_values"], {"IC50 (nM)": "9"})
        self.assertEqual(
            activity_evidence_errors(
                payload,
                [0],
                open_original=lambda: nullcontext(page.parent),
            ),
            [],
        )

    def test_id_header_context_and_value_disagreements_are_not_negative_role_claims(
        self,
    ):
        for different in (
            "identifier",
            "preparation",
            "header",
            "condition",
            "value",
            "foreign_cell",
            "swapped_view",
        ):
            with self.subTest(different=different):
                _page, region, source = self.fixture(different=different)
                self.assertFalse(
                    text_page_qualified(
                        source,
                        observed_page_text(source),
                        coordinate_regions=[region],
                    )
                )

    def test_scientific_conditions_are_not_hidden_inside_a_spectral_role(self):
        matrix = [
            ["Compound No.", "Preparation", "Characterization"],
            [
                "041B",
                "Prepared according to Compound 091C",
                "1H NMR (400 MHz) DMSO 7.0 ppm",
            ],
        ]
        self.assertIsNotNone(characterization_roles(matrix, PREFIX))
        for declaration in (
            "Target: JAK",
            "Assay: binding",
            "Cell line: HEK293",
            "Duration: 4 h",
            "Timepoint:",
            "Batch: A; Batch: B",
            "IC50 = 3 nM",
        ):
            with self.subTest(declaration=declaration):
                changed = copy.deepcopy(matrix)
                changed[1][2] += "; " + declaration
                self.assertIsNone(characterization_roles(changed, PREFIX))
                self.assertIsNone(
                    characterization_roles(matrix, PREFIX + "; " + declaration)
                )

    def test_weak_missing_crossing_or_competing_source_remains_unqualified(self):
        _page, region, source = self.fixture()
        for mutation in (
            "weak",
            "missing",
            "crossing",
            "competing",
            "old_role",
            "scientific_nomination",
        ):
            changed = copy.deepcopy(source)
            regions = [copy.deepcopy(region)]
            line = next(
                line for line in changed["lines"] if "DMSO" in line["nomination"]
            )
            if mutation == "weak":
                line["observations"][0]["confidence"] = 0.2
                line["observations"][0]["parts"][0]["confidence"] = 0.2
            elif mutation == "missing":
                line["observations"].pop()
            elif mutation == "crossing":
                # Keep the complete original line bounds; move only the owner.
                regions[0]["bbox"][0] = line["bbox"][0] + 1
            elif mutation == "competing":
                regions.append({**copy.deepcopy(region), "region_id": "f" * 32})
            elif mutation == "old_role":
                regions[0]["role_scope"]["version"] -= 1
            else:
                line["nomination"] += "; Duration: 4 h"
            with self.subTest(mutation=mutation):
                self.assertFalse(
                    text_page_qualified(
                        changed, observed_page_text(changed), coordinate_regions=regions
                    )
                )

    def test_independent_native_conditions_cannot_be_outvoted_by_optical_role(self):
        _page, region, _source = self.fixture()
        for original in ("Duration: 4 h", "Target: JAK", "Cell line:"):
            changed = copy.deepcopy(region)
            changed["role_scope"]["native_hints"][1][2] += "; " + original
            with self.subTest(original=original):
                self.assertFalse(valid_role_scope(changed))

    def test_removed_role_foreign_owner_or_missing_original_cannot_certify_the_page(
        self,
    ):
        page, region, source = self.fixture()
        payload = self.payload(region, source)
        self.assertTrue(original_activity_source_errors(payload))
        for mutation in ("role", "frame", "owner", "line"):
            changed = copy.deepcopy(payload)
            catalog = changed["coverage"]["text_sources"]["1"]
            line = next(
                line for line in catalog["lines"] if "DMSO" in line["nomination"]
            )
            if mutation == "role":
                del changed["coverage"]["regions"][0]["role_scope"]
            elif mutation == "frame":
                del line["observations"][0]["source_frame"]
            elif mutation == "owner":
                line["coordinate_owner"] = {
                    "role": "characterization",
                    "region_id": "f" * 32,
                }
            else:
                catalog["lines"].remove(line)
            with self.subTest(mutation=mutation):
                try:
                    errors = activity_evidence_errors(
                        changed, [0], open_original=lambda: nullcontext(page.parent)
                    )
                except (ValueError, TypeError):
                    continue
                self.assertTrue(errors)

    def test_changed_original_spectral_pixels_still_refuse_without_any_recognition(
        self,
    ):
        page, region, source = self.fixture()
        payload = self.payload(region, source)
        page.insert_text((340, 145), "IC50 = 3 nM", fontsize=8)
        self.assertTrue(
            original_activity_source_errors(
                payload,
                open_original=lambda: nullcontext(page.parent),
            )
        )


if __name__ == "__main__":
    unittest.main()
