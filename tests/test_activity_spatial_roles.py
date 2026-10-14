"""Native coordinate-path source roles; no private patent or mock grid parser."""

import copy
import unittest

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import coverage_errors, coverage_packet
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from patent_sar_extractor.core.activity_source_discovery import (
    discover_activity_sources,
)


def ruled(page, xs, ys, cells):
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.5)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.5)
    for row, values in enumerate(cells):
        for column, text in enumerate(values):
            result = page.insert_textbox(
                fitz.Rect(
                    xs[column] + 4, ys[row] + 4, xs[column + 1] - 4, ys[row + 1] - 3
                ),
                text,
                fontsize=9,
            )
            assert result >= 0, (
                "Controlled source text must fit, not silently disappear"
            )


def mixed_page(doc, *, titled=True, unknown=False):
    page = doc.new_page()
    if titled:
        page.insert_text((40, 70), "Table 17. Compound characterization", fontsize=10)
    ruled(
        page,
        [40, 140, 335, 555],
        [90, 120, 180, 240],
        [
            ["Compound No.", "Preparation", "Characterization"],
            [
                "73",
                "Synthesized in analogy to Compound 91",
                "1H NMR (400 MHz) 7.2 ppm; MS (ESI) m/z 413.1",
            ],
            [
                "84",
                "Synthesized in analogy to Compound 92",
                "13C NMR (100 MHz) 128.3 ppm; MS (ESI) m/z 427.1",
            ],
        ]
        if not unknown
        else [
            ["Compound No.", "Unreadable", "Unknown original column"],
            ["73", "?", "?"],
            ["84", "?", "?"],
        ],
    )
    page.insert_text((40, 295), "Example 18: Binding assay", fontsize=10)
    page.insert_text(
        (40, 312),
        "Cells were seeded and incubated. Results are shown in Table 88.",
        fontsize=9,
    )
    page.insert_text((40, 357), "Table 88. Binding activity", fontsize=10)
    ruled(
        page,
        [40, 160, 300],
        [375, 400, 425, 450],
        [
            ["Compound No.", "IC50 (nM)"],
            ["73", "7.4"],
            ["84", "9.1"],
        ],
    )
    return page


class ActivitySpatialRoleTests(unittest.TestCase):
    def parsed(self, **options):
        with fitz.open() as doc:
            mixed_page(doc, **options)
            return extract_coordinate_tables(doc, [0])

    def test_later_assay_does_not_turn_earlier_characterization_into_activity(self):
        for titled in (True, False):
            with self.subTest(titled=titled), fitz.open() as doc:
                mixed_page(doc, titled=titled)
                seeds = discover_activity_sources(doc, {})
                self.assertEqual(
                    seeds, [0]
                )  # The real later result must still be found.
                parsed = extract_coordinate_tables(doc, seeds)
                self.assertEqual(
                    {row.cpd for row in parsed.rows}, {"Compound 73", "Compound 84"}
                )
                self.assertEqual(len(parsed.rows), 2)
                self.assertFalse(
                    any(record["status"] == "unresolved" for record in parsed.coverage),
                    parsed.coverage,
                )
                self.assertTrue(
                    any(
                        record["reason"] == "observed_characterization"
                        for record in parsed.coverage
                    )
                )

    def test_characterization_role_is_revalidated_by_current_coverage(self):
        parsed = self.parsed()
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])
        role = next(
            record for record in packet["regions"] if record["status"] == "non_activity"
        )
        self.assertTrue(valid_role_scope(role))
        mutations = (
            lambda record: record["role_scope"].update(roles=None),
            lambda record: record["role_scope"].update(version=True),
            lambda record: record["role_scope"]["observations"][0]["matrix"][
                1
            ].__setitem__(2, "IC50 = 7 nM"),
            lambda record: record["role_scope"]["observations"][0]["cells"].pop(),
            lambda record: record["role_scope"]["native_hints"][1].__setitem__(
                2, "Kd (uM)"
            ),
            lambda record: record.pop("role_scope"),
        )
        for mutate in mutations:
            bad = copy.deepcopy(packet)
            record = next(
                item for item in bad["regions"] if item["status"] == "non_activity"
            )
            mutate(record)
            with (
                self.subTest(mutate=mutate),
                self.assertRaisesRegex(ValueError, "characterization"),
            ):
                coverage_errors(bad, [0], rows=parsed.rows)

    def test_characterization_does_not_resolve_a_missing_referenced_result(self):
        with fitz.open() as doc:
            page = mixed_page(doc)
            page.add_redact_annot(
                fitz.Rect(0, 340, page.rect.width, 500), fill=(1, 1, 1)
            )
            page.apply_redactions()
            parsed = extract_coordinate_tables(doc, [0])
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        errors = coverage_errors(packet, [0], rows=parsed.rows)
        self.assertTrue(any("Table 88" in error for error in errors), errors)

    def test_nonactivity_grid_alone_cannot_certify_an_activity_seed(self):
        with fitz.open() as doc:
            page = mixed_page(doc)
            page.add_redact_annot(
                fitz.Rect(0, 280, page.rect.width, 500), fill=(1, 1, 1)
            )
            page.apply_redactions()
            parsed = extract_coordinate_tables(doc, [0])
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        errors = coverage_errors(packet, [0], rows=parsed.rows)
        self.assertTrue(
            any("no_supported_activity_table" in error for error in errors), errors
        )

    def test_unknown_grid_is_not_silently_declared_characterization(self):
        with fitz.open() as doc:
            mixed_page(doc, titled=False, unknown=True)
            parsed = extract_coordinate_tables(doc, [0])
        self.assertTrue(
            any(record["status"] == "unresolved" for record in parsed.coverage)
        )
        self.assertFalse(
            any(
                record["reason"] == "observed_characterization"
                for record in parsed.coverage
            )
        )

    def test_nmr_binding_endpoint_is_still_an_activity_source(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((40, 75), "Table 38. NMR binding affinity", fontsize=10)
            ruled(
                page,
                [40, 160, 300],
                [90, 115, 140, 165],
                [
                    ["Compound No.", "Kd (uM)"],
                    ["73", "0.12"],
                    ["84", "0.31"],
                ],
            )
            parsed = extract_coordinate_tables(doc, [0])
        self.assertEqual(len(parsed.rows), 2)
        self.assertFalse(
            any(
                record["reason"] == "observed_characterization"
                for record in parsed.coverage
            )
        )
        self.assertFalse(
            any(record["status"] == "unresolved" for record in parsed.coverage)
        )

    def test_existing_engine_proves_raster_characterization_without_claiming_activity(
        self,
    ):
        from patent_sar_extractor.core.activity_grid_role_observation import (
            observe_characterization,
        )
        from patent_sar_extractor.core.table_geometry import (
            detect_ruled_table_regions,
            page_tokens,
        )

        with fitz.open() as native, fitz.open() as raster:
            source = mixed_page(native)
            pixmap = source.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = raster.new_page(width=source.rect.width, height=source.rect.height)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
            tokens = page_tokens(page, dpi=240, allow_tesseract=False)
            regions = sorted(
                detect_ruled_table_regions(page, dpi=240),
                key=lambda region: region["ys"][0],
            )
            self.assertEqual(len(regions), 2)
            proof = observe_characterization(
                page, regions[0], tokens, "Table 17. Compound characterization"
            )
        self.assertIsNotNone(proof)
        record = {
            "bbox": [proof["xs"][0], proof["ys"][0], proof["xs"][-1], proof["ys"][-1]],
            "role_scope": proof,
        }
        self.assertTrue(valid_role_scope(record))
        self.assertEqual(
            [o["method"] for o in proof["observations"]],
            ["cell_ocr_400dpi", "cell_ocr_600dpi"],
        )

    def test_actual_raster_coordinate_path_retains_real_later_measurements(self):
        with fitz.open() as native, fitz.open() as raster:
            source = mixed_page(native)
            pixmap = source.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = raster.new_page(width=source.rect.width, height=source.rect.height)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
            parsed = extract_coordinate_tables(raster, [0])
        self.assertTrue(
            any(
                record["reason"] == "observed_characterization"
                for record in parsed.coverage
            ),
            parsed.coverage,
        )
        self.assertEqual(len(parsed.rows), 2)
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])

    def test_partial_native_activity_header_cannot_be_outvoted_by_raster_role(self):
        from patent_sar_extractor.core.activity_grid_role_observation import (
            observe_characterization,
        )
        from patent_sar_extractor.core.table_geometry import (
            detect_ruled_table_regions,
            page_tokens,
        )

        with fitz.open() as native, fitz.open() as raster:
            source = mixed_page(native)
            pixmap = source.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = raster.new_page(width=source.rect.width, height=source.rect.height)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
            page.insert_text((340, 108), "IC50 (nM)", fontsize=9, render_mode=3)
            page.insert_text((40, 800), "Native footer", fontsize=9)
            tokens = page_tokens(page, dpi=240, allow_tesseract=False)
            region = min(
                detect_ruled_table_regions(page, dpi=240),
                key=lambda item: item["ys"][0],
            )
            self.assertIsNone(
                observe_characterization(
                    page, region, tokens, "Table 17. Compound characterization"
                )
            )
