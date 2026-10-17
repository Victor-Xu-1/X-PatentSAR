"""Original characterization references cannot become standalone diagram titles."""

import copy
import unittest

import fitz
from test_activity_spatial_roles import ruled

from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.binding_source_regions import reference_regions


def characterization_page(doc, *, unknown=False, standalone=False):
    page = doc.new_page(width=560, height=700)
    page.insert_text((40, 70), "Table 17. Compound characterization", fontsize=10)
    ruled(
        page,
        [40, 140, 315, 530],
        [90, 120, 185, 250],
        [
            ["Compound No.", "Preparation", "Characterization"],
            [
                "Compound 73",
                "Synthesized in analogy to\nCompound 91",
                "1H NMR (400 MHz) 7.2 ppm;\nMS (ESI) m/z 413.1",
            ],
            [
                "Compound 84",
                "Prepared in analogy to\nCompound 92",
                "13C NMR (100 MHz) 128.3 ppm;\nMS (ESI) m/z 427.1",
            ],
        ]
        if not unknown
        else [
            ["Compound No.", "Original unknown column", "Unknown"],
            ["Compound 73", "Unknown parameter\nCompound 91", "?"],
            ["Compound 84", "Unknown parameter\nCompound 92", "?"],
        ],
    )
    if standalone:
        page.insert_text((40, 300), "Compound 63: Preparation", fontsize=10)
        page.draw_polyline(
            [
                (80, 340),
                (110, 320),
                (140, 340),
                (140, 370),
                (110, 390),
                (80, 370),
                (80, 340),
            ]
        )
        page.insert_text((40, 450), "Step 1: Intermediate synthesis", fontsize=10)
    return page


class HeadingCharacterizationRoleTests(unittest.TestCase):
    def test_open_bottom_characterization_row_keeps_primary_and_method_roles(self):
        with fitz.open() as doc:
            page = characterization_page(doc)
            # Original side/column rules continue below the last closed row.
            # There is no invented bottom edge and no complete-cell QA claim.
            for x in (40, 140, 315, 530):
                page.draw_line((x, 250), (x, 340))
            page.insert_text((48, 270), "Compound 105", fontsize=9)
            page.insert_text(
                (148, 270), "Prepared in analogy to\nCompound 118", fontsize=9
            )
            page.insert_text(
                (325, 270), "1H NMR (400 MHz) 7.3 ppm;\nMS (ESI) m/z 441.1", fontsize=9
            )
            sections = []
            blocks = observed_heading_blocks(doc, [0], {}, source_sections=sections)
        with self.subTest(role="method reference"):
            self.assertNotIn("Compound 118", [block["cpd"] for block in blocks])
        with self.subTest(role="original primary identifier"):
            self.assertTrue(
                any(
                    section["role"] == "characterization_identifier"
                    and section["identifier"] == "105"
                    for section in sections
                ),
                "The visible primary original identifier must not disappear with its open row",
            )

    def test_native_preparation_references_remain_source_not_new_headings(self):
        with fitz.open() as doc:
            characterization_page(doc)
            sections = []
            blocks = observed_heading_blocks(doc, [0], {}, source_sections=sections)
        self.assertEqual(blocks, [], blocks)
        references = [s for s in sections if s["role"] == "characterization_reference"]
        self.assertTrue(references, sections)
        self.assertTrue(any("91" in s["line_text"] for s in references))
        self.assertTrue(all(s.get("source_region") for s in references))

    def test_a_real_title_outside_the_reference_grid_is_not_excluded(self):
        with fitz.open() as doc:
            characterization_page(doc, standalone=True)
            blocks = observed_heading_blocks(doc, [0], {})
        self.assertEqual([b["cpd"] for b in blocks], ["Compound 63"])

    def test_unknown_grid_labels_do_not_gain_a_reference_exemption(self):
        with fitz.open() as doc:
            characterization_page(doc, unknown=True)
            sections = []
            blocks = observed_heading_blocks(doc, [0], {}, source_sections=sections)
        self.assertTrue(blocks)
        self.assertFalse(
            any(s["role"] == "characterization_reference" for s in sections)
        )

    def observed(self):
        with fitz.open() as doc:
            characterization_page(doc)
            sections = []
            observed_heading_blocks(doc, [0], {}, source_sections=sections)
        return {
            "source_sections": sections,
            "source_reference_scope": reference_scope(sections),
        }

    def test_primary_ids_remain_required_but_method_references_are_not_molecules(self):
        payload = self.observed()
        entries = [{"cpd": "Compound 73"}, {"cpd": "Compound 84"}]
        self.assertEqual(reference_issues(payload, entries), [])
        issues = reference_issues(payload, entries[:1])
        self.assertEqual([issue["cpd"] for issue in issues], ["Compound 84"])
        self.assertNotIn("Compound 91", str(issues))

    def test_omitting_a_primary_reference_cannot_hide_missing_structures(self):
        payload = self.observed()
        payload["source_sections"] = [
            s
            for s in payload["source_sections"]
            if s["role"] != "characterization_identifier"
        ]
        with self.assertRaises(ValueError):
            reference_issues(payload, [])

    def test_foreign_original_and_rehashed_invalid_roles_are_rejected(self):
        from patent_sar_extractor.core.activity_header_evidence import proof_id

        baseline = self.observed()
        for change in ("foreign", "role"):
            payload = copy.deepcopy(baseline)
            section = next(
                s
                for s in payload["source_sections"]
                if s["role"] == "characterization_region"
            )
            region = section["source_region"]
            if change == "foreign":
                region["original_pdf_sha256"] = "0" * 64
            else:
                region["role_scope"]["roles"]["columns"][1] = "identifier"
            previous = region["region_id"]
            region["region_id"] = proof_id(
                {k: v for k, v in region.items() if k != "region_id"}
            )
            payload["source_reference_scope"]["region_ids"] = [region["region_id"]]
            for entry in payload["source_sections"]:
                if entry.get("source_region") == previous:
                    entry["source_region"] = region["region_id"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                reference_issues(payload, [])

    def test_locator_only_full_width_box_cannot_exempt_a_reference(self):
        from patent_sar_extractor.core.binding_source_regions import reference_cell

        with fitz.open() as doc:
            page = characterization_page(doc)
            regions = reference_regions(page, original_pdf_sha256="a" * 64)
            cell = regions[0]["role_scope"]
            line = {
                "bbox": [
                    cell["xs"][1] + 1,
                    cell["ys"][1] + 1,
                    cell["xs"][2] - 1,
                    cell["ys"][2] - 1,
                ],
                "text": "Compound 91",
            }
            self.assertIsNone(reference_cell(line, regions))

    def test_wrapper_gap_is_literal_but_parent_and_split_digit_references_are_not(self):
        from patent_sar_extractor.core.binding_source_regions import reference_cell

        with fitz.open() as doc:
            page = characterization_page(doc)
            regions = reference_regions(page, original_pdf_sha256="a" * 64)
            scope = regions[0]["role_scope"]
            line = {
                "bbox": [
                    scope["xs"][1] + 2,
                    scope["ys"][1] + 2,
                    scope["xs"][2] - 2,
                    scope["ys"][2] - 2,
                ],
                "source": "page_ocr",
                "geometry_space": "rendered",
            }
            self.assertIsNotNone(
                reference_cell({**line, "text": "Compound91"}, regions)
            )
            for text in ("Compound 9", "Compound 9 1", "Compound 91A", "Compound 91-2"):
                with self.subTest(text=text):
                    self.assertIsNone(reference_cell({**line, "text": text}, regions))

    def test_explicit_intermediate_cells_are_preserved_without_terminal_invention(self):
        for kind in ("Intermediate", "Compound"):
            with self.subTest(kind=kind), fitz.open() as doc:
                page = doc.new_page(width=560, height=700)
                page.insert_text((40, 70), "Table 28. Compound characterization")
                ruled(
                    page,
                    [40, 175, 355, 530],
                    [90, 120, 205],
                    [
                        ["Intermediate No.", "Preparation", "Characterization"],
                        [
                            f"{kind} I-73",
                            "Synthesized in analogy to Compound 91",
                            "1H NMR (400 MHz) 7.2 ppm; MS (ESI) m/z 413.1",
                        ],
                    ],
                )
                sections = []
                observed_heading_blocks(doc, [0], {}, source_sections=sections)
                payload = {
                    "source_sections": sections,
                    "source_reference_scope": reference_scope(sections),
                }
                cells = [
                    s for s in sections if s["role"] == "characterization_identifier"
                ]
                self.assertEqual(len(cells), 1)
                self.assertEqual(cells[0]["identifier"], "I-73")
                if kind == "Intermediate":
                    self.assertEqual(cells[0]["source_role"], "intermediate")
                    self.assertEqual(reference_issues(payload, []), [])
                else:
                    self.assertEqual(cells[0]["source_role"], "ambiguous")
                    self.assertTrue(reference_issues(payload, []))

    def test_boolean_coordinates_and_oversized_section_ledgers_are_rejected(self):
        baseline = self.observed()
        for role in ("characterization_identifier", "characterization_reference"):
            payload = copy.deepcopy(baseline)
            entry = next(s for s in payload["source_sections"] if s["role"] == role)
            entry["grid_row"] = True
            with self.subTest(role=role), self.assertRaises(ValueError):
                reference_issues(payload, [])
        with self.assertRaises(ValueError):
            reference_issues({"source_sections": [{"role": "unknown"}] * 25001}, [])

    def test_core_and_web_replay_omitted_references_after_issues_are_cleared(self):
        import json
        import tempfile
        from pathlib import Path

        from patent_sar_extractor.core.formal_structure import coverage_errors
        from patent_sar_extractor.web.compound_catalog import read_compound_catalog
        from patent_sar_extractor.web.errors import WebError
        from tests.test_source_led_export import run_fixture

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_fixture(root)
            payload = json.loads(
                (root / "structure_bindings/bindings.json").read_text()
            )
            payload.update(self.observed())
            payload["source_issues"] = []
            self.assertTrue(
                any(
                    "characterization references" in error
                    for error in coverage_errors(payload)
                )
            )
            payload["source_sections"] = [
                s
                for s in payload["source_sections"]
                if s["role"] != "characterization_identifier"
            ]
            with self.assertRaises(ValueError):
                coverage_errors(payload)
            with self.assertRaises(WebError):
                read_compound_catalog(
                    payload, [{"structure_id": "S42"}, {"structure_id": "S42A"}]
                )

    def test_characterization_outside_candidate_pages_still_reports_missing_products(
        self,
    ):
        import tempfile
        from pathlib import Path

        from patent_sar_extractor.core.structure_binder import bind
        from tests.test_binding_modules import BindingModuleTests

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, metadata, profile = BindingModuleTests().pdf_fixture(
                root, extra_caption=True
            )
            with fitz.open(pdf) as doc:
                characterization_page(doc)
                doc.saveIncr()
            result = bind(str(pdf), profile, str(root / "binding"), str(metadata))
            self.assertEqual(result["bound"], 3)
            self.assertEqual(
                {issue["cpd"] for issue in result["source_issues"]},
                {"Compound 73", "Compound 84"},
            )
            self.assertTrue(
                all(
                    issue["reason"]
                    == "characterization_identifier_without_proved_structure"
                    for issue in result["source_issues"]
                )
            )
            regions = [
                s["source_region"]
                for s in result["source_sections"]
                if s["role"] == "characterization_region"
            ]
            self.assertEqual([region["page_no"] for region in regions], [3])

    def test_real_raster_and_native_footer_share_original_reference_authority(self):
        from patent_sar_extractor.core.binding_ocr import _get_ocr_line_observations

        with fitz.open() as original:
            page = characterization_page(original)
            raster = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False).tobytes(
                "png"
            )
        for footer in (False, True):
            with self.subTest(footer=footer), fitz.open() as doc:
                page = doc.new_page(width=560, height=700)
                page.insert_image(fitz.Rect(0, 0, 560, 660), stream=raster)
                if footer:
                    page.insert_text((40, 690), "Native footer only", fontsize=8)
                lines = _get_ocr_line_observations(page)
                self.assertTrue(
                    any(
                        line.get("source") == "page_ocr" and line.get("bbox")
                        for line in lines
                    )
                )
                sections = []
                blocks = observed_heading_blocks(
                    doc, [0], {}, source_sections=sections, source_line_map={0: lines}
                )
                self.assertEqual(blocks, [], blocks)
                payload = {
                    "source_sections": sections,
                    "source_reference_scope": reference_scope(sections),
                }
                self.assertEqual(
                    reference_issues(
                        payload, [{"cpd": "Compound 73"}, {"cpd": "Compound 84"}]
                    ),
                    [],
                )
                self.assertEqual(
                    {
                        s["identifier"]
                        for s in sections
                        if s["role"] == "characterization_identifier"
                    },
                    {"73", "84"},
                )


if __name__ == "__main__":
    unittest.main()
